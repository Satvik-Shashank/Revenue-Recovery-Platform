"""ImpulseEngine: the orchestrator. Event in -> identity -> passport -> module -> Kernel -> action -> ledger.

State is held in memory (deterministically seedable). On serverless each warm instance seeds the same demo
world; production persistence would put the ledger/bandit/passports in Postgres (see docs)."""

import hashlib
import json
import random
import time
from datetime import datetime, timezone

from .actions import ActionLayer
from .adapters import MappingError
from .billing import LatenessModel, PromiseTracker, collections_worklist, demo_billing_data, run_assurance
from .clawback import (analyse_dispute, assemble_evidence_pack, canonical_to_payload, deadline_status,
                       dispute_candidates)
from .identity import IdentityResolver
from .ingest import IngestionHub
from .kernel import Case, Kernel
from .ledger import Ledger
from .passport import DAY, build_passport, empty_history, ts
from .payments import (RetryBandit, build_journey, payment_candidates, predunning_targets, routing_advice)
from .policy import Policy
from .refunds import refund_candidates
from .retention import persuadability, retention_candidates, winback_candidates
from .rto import rto_candidates
from .schema import (Customer, Dispute, EngagementEvent, Invoice, Order, PaymentAttempt, PaymentMethod, Refund,
                     Shipment, Subscription)
from .sim import true_link_p, true_retry_p

NOOP = {"do_nothing", "ship_as_is"}
LEAK_OF = {"payments": "failed", "clawback": "clawed_back", "refunds": "clawed_back", "rto": "clawed_back",
           "retention": "stopped", "billing": "missed"}


def _h(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16)


class ImpulseEngine:
    def __init__(self, seed: int = 7):
        self.seed = seed
        self._clock: float | None = None
        self.policy = Policy()
        self.kernel = Kernel(self.policy)
        self.kernel.ctx.now = self.now
        self.hub = IngestionHub()
        self.resolver = IdentityResolver()
        self.actions = ActionLayer()
        self.ledger = Ledger(fee_pct=self.policy["fee_pct"])
        self.bandit = RetryBandit(seed=seed)
        self.history: dict[str, dict] = {}
        self.cases: dict[str, dict] = {}
        self.approvals: dict[str, dict] = {}
        self.audit_log: list[dict] = []
        self.webhook_urls: list[str] = []
        self.outbox: list[dict] = []
        self.payment_index: dict[str, str] = {}     # payment id -> customer id
        self.order_index: dict[str, str] = {}
        self.retry_counts: dict[str, int] = {}
        self.chains: dict[str, dict] = {}            # active payment-recovery chains (one ledger row each)
        self.promises = PromiseTracker()
        self._billing = None
        self._merges_seen = 0

    # ── time ────────────────────────────────────────────────────────────────
    def now(self) -> float:
        return self._clock if self._clock is not None else time.time()

    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.now(), timezone.utc)

    def set_clock(self, t: float | None):
        self._clock = t

    # ── plumbing ────────────────────────────────────────────────────────────
    def audit(self, actor: str, event: str, detail: dict | None = None):
        self.audit_log.append({"at": self.now(), "actor": actor, "event": event, "detail": detail or {}})
        del self.audit_log[:-2000]

    def hist(self, customer_id: str) -> dict:
        return self.history.setdefault(self.resolver.canonical(customer_id), empty_history())

    def _consolidate(self):
        """After identity merges, fold the absorbed customer's history into the surviving record."""
        for m in self.resolver.audit[self._merges_seen:]:
            if m["action"] != "merge":
                continue
            src = self.history.pop(m["absorbed"], None)
            if src:
                dst = self.history.setdefault(m["keep"], empty_history())
                for k, v in src.items():
                    if isinstance(v, list):
                        dst[k].extend(v)
                    elif isinstance(v, set):
                        dst[k] |= v
                    elif isinstance(v, (int, float)) and not isinstance(v, bool):
                        dst[k] += v
                    elif isinstance(v, bool):
                        dst[k] = dst[k] or v
            self.audit("system", "identity_merge", {"keep": m["keep"], "absorbed": m["absorbed"], "reason": m["reason"]})
        self._merges_seen = len(self.resolver.audit)

    def passport(self, customer_id: str) -> dict:
        root = self.resolver.canonical(customer_id)
        return build_passport(root, self.resolver.profile(root), self.hist(root), self.now())

    def model_versions(self) -> dict:
        return {"classifier": "lightgbm-calibrated", "win_predictor": "lightgbm-calibrated", "retry_bandit": f"ucb-v1 (n={self.bandit.observations()})",
                "churn": "weighted-v1", "refund_abuse": "weighted-v1", "rto": "weighted-v1", "policy_version": self.policy["version"]}

    # ── ingestion ───────────────────────────────────────────────────────────
    def ingest(self, source: str, body: bytes, signature: str | None = None) -> dict:
        res = self.hub.receive(source, body, signature)
        out = {"status": res["status"], "event_id": res.get("event_id"), "cases": []}
        for k in ("reason", "error", "dead_letter_id"):
            if k in res:
                out[k] = res[k]
        if res["status"] == "processed":
            out["cases"] = [c["case_id"] for c in self.apply_entities(res["entities"])]
            out["entities"] = [type(e).__name__ for e in res["entities"]]
            out["customer_ids"] = sorted({self.resolver.canonical(e.customer_id) for e in res["entities"] if hasattr(e, "customer_id")})
        self.audit("webhook", f"ingest:{res['status']}", {"source": source, "event_id": res.get("event_id")})
        return out

    def replay_dead_letter(self, dl_id: str, patched: dict | None = None) -> dict:
        res = self.hub.replay(dl_id, patched)
        out = {"status": res["status"], "cases": []}
        if res["status"] == "processed":
            out["cases"] = [c["case_id"] for c in self.apply_entities(res["entities"])]
        self.audit("operator", "dead_letter_replay", {"id": dl_id, "status": res["status"]})
        return out

    def apply_entities(self, entities: list) -> list[dict]:
        """Resolve identity, store history, then dispatch to the relevant engine. Returns opened case records."""
        methods = [e for e in entities if isinstance(e, PaymentMethod)]
        fp = next((m.fingerprint for m in methods if m.fingerprint), None)
        mapping = {}
        for e in entities:
            if isinstance(e, Customer):
                mapping[e.id] = self.resolver.resolve(e, fp)
        self._consolidate()
        opened = []
        for e in entities:
            if isinstance(e, (Customer, Shipment)) or not hasattr(e, "customer_id"):
                continue
            root = mapping.get(e.customer_id) or self.resolver.canonical(e.customer_id)
            if isinstance(e, (Dispute, Refund)) and e.payment_id in self.payment_index:
                root = self.resolver.canonical(self.payment_index[e.payment_id])
            e.customer_id = root
        if fp and mapping:
            self.resolver.register_fingerprint(next(iter(mapping.values())), fp)
            self._consolidate()
        for e in entities:
            if isinstance(e, Customer):
                self.hist(mapping[e.id])
            elif isinstance(e, PaymentMethod):
                self.hist(e.customer_id)["methods"].append(e)
            elif isinstance(e, PaymentAttempt):
                if e.id in self.payment_index:
                    continue
                self.payment_index[e.id] = e.customer_id
                self.hist(e.customer_id)["attempts"].append(e)
                opened += self._on_attempt(e)
            elif isinstance(e, Subscription):
                h = self.hist(e.customer_id)
                h["subscriptions"] = [s for s in h["subscriptions"] if s.id != e.id] + [e]
                opened += self.evaluate_retention(e.customer_id)
            elif isinstance(e, Invoice):
                self.hist(e.customer_id)["invoices"].append(e)
            elif isinstance(e, Refund):
                self.hist(e.customer_id)["refunds"].append(e)
                opened += self._on_refund(e)
            elif isinstance(e, Dispute):
                self.hist(e.customer_id)["disputes"].append(e)
                opened += self._on_dispute(e)
            elif isinstance(e, Order):
                self.order_index[e.id] = e.customer_id
                self.hist(e.customer_id)["orders"].append(e)
                opened += self._on_order(e)
            elif isinstance(e, EngagementEvent):
                h = self.hist(e.customer_id)
                h["engagement"].append(e)
                if e.type == "offer_taken":
                    h["offers_taken"] += 1
                opened += self.evaluate_retention(e.customer_id)
        for e in entities:
            if isinstance(e, Shipment) and e.order_id in self.order_index:
                self.hist(self.order_index[e.order_id])["shipments"].append(e)
        return opened

    # ── case machinery ──────────────────────────────────────────────────────
    def _open_case(self, case: Case, cands: list, meta: dict, *, kind: str, arm: str = "treatment",
                   extra: dict | None = None, features_view: dict | None = None) -> dict:
        dec = self.kernel.decide(case, cands, self.model_versions())
        rec = {"case_id": case.id, "module": case.module, "kind": kind, "customer_id": case.customer_id, "amount": case.amount,
               "created_at": self.now(), "arm": arm, "decision": dec.to_dict(), "meta": meta, "status": None,
               "action_id": None, "outcome": None, "resolved_at": None,
               "candidates": [{"action": c.action, "label": c.label, "ev": round(c.ev, 2), "p": round(c.p_success, 3),
                               "params": c.params, "category": c.category, "channel": c.channel} for c in cands],
               "features": features_view or case.features, "deadline": case.deadline, "_case": case, "_cands": cands,
               **(extra or {})}
        ch = dec.chosen
        if dec.mode == "skip" or (ch and ch["action"] in NOOP):
            rec["status"] = "no_action"
        elif arm == "holdout":
            rec["status"] = "holdout"
        elif dec.mode == "auto":
            self._execute(rec, case, dec)
        elif dec.mode == "approve":
            action = self.actions.execute(case, dec, status="pending_approval")
            rec["action_id"], rec["status"] = action["id"], "pending_approval"
            self.approvals[f"apr_{case.id}"] = {
                "id": f"apr_{case.id}", "case_id": case.id, "decision_id": dec.id, "module": case.module,
                "customer_id": case.customer_id, "action": ch["action"], "label": ch["label"], "amount": case.amount,
                "ev": dec.ev, "reason": dec.reason, "rejected": dec.rejected, "status": "pending", "created_at": self.now(),
                "alternatives": [{"action": c["action"], "label": c["label"], "ev": c["ev"]} for c in rec["candidates"]
                                 if c["action"] not in NOOP]}
        else:
            rec["status"] = "recommended"
        self.cases[case.id] = rec
        if rec["status"] in ("active", "pending_approval"):
            self.hist(case.customer_id)["actions"].append({"at": self.now(), "action": ch["action"], "status": "pending_approval"
                                                          if rec["status"] == "pending_approval" else "executed", "case": case.id})
        self._emit("decision.created", {"case_id": case.id, "module": case.module, "mode": dec.mode,
                                        "action": ch["action"] if ch else None, "ev": dec.ev, "reason": dec.reason})
        return rec

    def _execute(self, rec: dict, case: Case, dec) -> dict:
        action = self.actions.execute(case, dec, status="executed")
        self.kernel.commit(case, dec)
        rec["action_id"], rec["status"] = action["id"], "active"
        if dec.chosen["action"] == "schedule_retry":
            key = case.features.get("chain") or case.customer_id
            self.retry_counts[key] = self.retry_counts.get(key, 0) + 1
        return action

    def decide_approval(self, approval_id: str, verdict: str, edit_action: str | None = None, actor: str = "merchant") -> dict:
        apr = self.approvals[approval_id]
        if apr["status"] != "pending":
            raise ValueError(f"approval already {apr['status']}")
        rec = self.cases[apr["case_id"]]
        case, dec = rec["_case"], None
        from .kernel import Decision
        dd = rec["decision"]
        dec = Decision(**{k: v for k, v in dd.items()})
        if verdict == "reject":
            apr["status"], rec["status"] = "rejected", "rejected"
            self.actions.set_status(rec["action_id"], "rejected")
        elif verdict in ("approve", "edit"):
            if verdict == "edit":
                alt = next((c for c in rec["_cands"] if c.action == edit_action), None)
                if not alt:
                    raise ValueError(f"unknown alternative: {edit_action}")
                from dataclasses import asdict
                dec.chosen = {**asdict(alt), "ev": round(alt.ev, 2)}
                dec.reason = f"Edited by {actor}: {alt.label} (originally {apr['action']}). " + dec.reason
                rec["decision"] = dec.to_dict()
                apr["status"], apr["edited_to"] = "edited", edit_action
                self.actions.records.pop(rec["action_id"], None)
                self.actions.by_key.pop(f"{case.id}:{apr['action']}", None)
                action = self.actions.execute(case, dec, status="executed")
                rec["action_id"] = action["id"]
            else:
                apr["status"] = "approved"
                self.actions.set_status(rec["action_id"], "executed")
            self.kernel.commit(case, dec)
            rec["status"] = "active"
            if dec.chosen["action"] == "schedule_retry":
                key = case.features.get("chain") or case.customer_id
                self.retry_counts[key] = self.retry_counts.get(key, 0) + 1
        else:
            raise ValueError("verdict must be approve, edit or reject")
        apr["resolved_at"], apr["resolved_by"] = self.now(), actor
        self.audit(actor, f"approval:{apr['status']}", {"approval": approval_id, "case": apr["case_id"], "action": apr["action"]})
        self._emit("approval.resolved", {"approval_id": approval_id, "status": apr["status"], "case_id": apr["case_id"]})
        return apr

    def _emit(self, event: str, payload: dict):
        item = {"id": f"evt_{len(self.outbox) + 1}", "event": event, "payload": payload, "at": self.now(), "delivery": "queued"}
        self.outbox.append(item)
        del self.outbox[:-500]
        if self.webhook_urls:
            self._deliver(item)

    def _deliver(self, item: dict):
        try:
            import httpx
            body = json.dumps({k: item[k] for k in ("id", "event", "payload")}, default=str)
            sig = hashlib.sha256(body.encode()).hexdigest()
            for url in self.webhook_urls:
                httpx.post(url, content=body, headers={"content-type": "application/json", "x-impulse-signature": sig}, timeout=2.0)
            item["delivery"] = "delivered"
        except Exception as exc:
            item["delivery"] = f"failed: {type(exc).__name__}"

    # ── module handlers ─────────────────────────────────────────────────────
    def _on_attempt(self, a: PaymentAttempt) -> list[dict]:
        opened = []
        if a.status == "succeeded":
            # a real success closes any open recovery case for this customer/subscription: a REAL outcome
            for rec in list(self.cases.values()):
                if rec["module"] == "payments" and rec["status"] == "active" and self.resolver.canonical(rec["customer_id"]) == a.customer_id \
                        and rec["features"].get("chain") == (a.subscription_id or a.customer_id):
                    self.resolve_case(rec["case_id"], {"success": True, "recovered": rec["amount"], "source": "webhook"})
            self.evaluate_retention(a.customer_id)
            return opened
        if a.status != "failed":
            return opened
        chain = a.subscription_id or a.customer_id
        if chain in self.chains:            # a real retry failed: the chain continues
            st = self.chains[chain]
            for r in list(self.cases.values()):
                if r["module"] == "payments" and r["status"] == "active" and r["features"].get("chain") == chain:
                    self.resolve_case(r["case_id"], {"success": False, "recovered": 0, "source": "webhook"}, advance=False)
            rec = self._decide_payment(a, chain, st["root"], st["steps"] + 1)
        else:
            rec = self._decide_payment(a, chain, None, 1)
        opened.append(rec)
        opened += self.evaluate_retention(a.customer_id)
        return opened

    def _decide_payment(self, a: PaymentAttempt, chain: str, root: str | None, step: int) -> dict:
        now = self.dt()
        passport = self.passport(a.customer_id)
        st = self.chains.get(chain)
        if st and st["extra_streak"]:
            passport["payment_health"] = {**passport["payment_health"],
                                          "failure_streak": passport["payment_health"]["failure_streak"] + st["extra_streak"]}
            passport["churn_risk"] = min(0.95, passport["churn_risk"] + 0.12 * st["extra_streak"])
        retries = self.retry_counts.get(chain, 0)
        cands, meta = payment_candidates(a, passport, self.bandit, self.policy, now, retries_so_far=retries)
        if st:
            cands = [c for c in cands if c.action in ("schedule_retry", "do_nothing") or c.action not in st["used"]]
        arm = st["arm"] if st else ("holdout" if _h(a.id) % 100 < self.policy["holdout_pct"] else "treatment")
        case = Case("payments", a.customer_id, a.amount, {"decline_category": a.decline_category, "decline_code": a.decline_code,
                                                          "retries_so_far": retries, "chain": chain, "payment_id": a.id, "step": step,
                                                          "gateway": a.gateway, "recurring": a.is_recurring,
                                                          "customer_name": passport["profile"].get("name") or "there"},
                    passport, kind="failed_payment" if step == 1 else "recovery_follow_up")
        if step == 1:
            self.chains[chain] = {"root": case.id, "cost": 0.0, "steps": 1, "used": set(), "arm": arm, "amount": a.amount,
                                  "extra_streak": 0, "customer_id": a.customer_id, "trail": []}
        else:
            self.chains[chain]["steps"] = step
        rec = self._open_case(case, cands, meta, kind=case.kind, arm=arm, extra={"attempt": a, "chain_root": root or case.id})
        ch = rec["decision"]["chosen"]
        rec["journey"] = build_journey(a, ch, passport, now)
        if ch and rec["status"] in ("active", "pending_approval"):
            self.chains[chain]["used"].add(ch["action"])
        if rec["status"] == "no_action":
            self._finalize_chain(chain, False, rec)
        return rec

    def _finalize_chain(self, chain: str, success: bool, rec: dict, pause: bool = False):
        """One ledger row per failed payment: the whole journey, not each step."""
        st = self.chains.pop(chain, None)
        if not st:
            return
        root = self.cases.get(st["root"], rec)
        dec = rec["decision"]
        treat = st["arm"] == "treatment"
        self.ledger.record(case_id=st["root"], module="payments", action="recovery_journey" if treat else "merchant_baseline",
                           amount_at_stake=st["amount"], recovered=st["amount"] if success else 0.0, cost=st["cost"] if treat else 0.0,
                           arm=st["arm"], customer_id=st["customer_id"], at=self.now(),
                           receipt={"reason": dec["reason"], "rejected": dec["rejected"], "guardrails": dec["guardrails_triggered"],
                                    "model_versions": dec["model_versions"], "policy_version": dec["policy_version"], "mode": dec["mode"],
                                    "steps": st["trail"], "inputs": {"decline_code": root["features"].get("decline_code"), "amount": st["amount"]},
                                    "outcome_simulated": any(t.get("simulated") for t in st["trail"])})
        if success:
            self.hist(st["customer_id"])["recovered_ids"].add(root["features"].get("payment_id"))
        self._emit("outcome.recorded", {"case_id": st["root"], "module": "payments",
                                        "recovered": st["amount"] if success else 0.0, "arm": st["arm"]})

    def evaluate_retention(self, customer_id: str) -> list[dict]:
        root = self.resolver.canonical(customer_id)
        h = self.hist(root)
        if not h["subscriptions"]:
            return []
        passport = self.passport(root)
        fusion = passport["fusion"]
        open_ret = [r for r in self.cases.values() if r["module"] == "retention" and r["status"] in ("active", "pending_approval", "recommended")
                    and self.resolver.canonical(r["customer_id"]) == root]
        if open_ret and (not fusion or any(r["kind"] == "compound" for r in open_ret)):
            return []
        canceled = all(s.status == "canceled" for s in h["subscriptions"])
        if canceled:
            cands = winback_candidates(passport, self.policy)
            at_risk = passport["monthly_revenue"] * 6
        elif passport["churn_risk"] >= 0.35 or fusion:
            cands = retention_candidates(passport, self.policy)
            at_risk = passport["churn_risk"] * passport["value_score"]
            if fusion:
                # several leaks at once: treat as ONE relationship at risk, not N automated cases
                at_risk = max(at_risk, fusion["exposure"])
                for c in cands:
                    if c.action == "personal_outreach":
                        c.p_success, c.value, c.note = 0.6, at_risk, fusion["explanation"]
                    elif c.category in ("communication", "commercial"):
                        c.risk_cost += 0.12 * at_risk   # automated nudges in the middle of a multi-signal problem can make it worse
                if not any(c.action == "personal_outreach" for c in cands):
                    from .kernel import Candidate
                    cands.append(Candidate("personal_outreach", "Personal outreach call", p_success=0.6, value=at_risk, cost=180,
                                           category="internal", note=fusion["explanation"]))
        else:
            return []
        for r in open_ret:
            r["status"], r["superseded_by"] = "superseded", "compound"
        kind = "win_back" if canceled else ("compound" if fusion else "save")
        case = Case("retention", root, at_risk, {"churn_type": passport["churn_type"], "reasons": passport["churn_reasons"],
                                                 "persuadability": persuadability(passport), "customer_name": passport["profile"].get("name") or "there"},
                    passport, kind=kind)
        rec = self._open_case(case, cands, {"churn_risk": passport["churn_risk"], "churn_type": passport["churn_type"],
                                            "reasons": passport["churn_reasons"], "persuadability": persuadability(passport),
                                            "fusion": fusion}, kind=kind)
        if fusion:
            for r in self.cases.values():
                if r is not rec and r["status"] in ("active", "pending_approval", "recommended") and self.resolver.canonical(r["customer_id"]) == root:
                    r["fused_into"] = rec["case_id"]
        return [rec]

    def _dispute_context(self, d: Dispute) -> dict:
        h = self.hist(d.customer_id)
        order = h["orders"][-1] if h["orders"] else None
        ship = next((s for s in h["shipments"] if order and s.order_id == order.id), None)
        prof = self.resolver.profile(d.customer_id)
        created = ts(prof.get("created_at"), default=self.now() - 30 * DAY)
        return {"order": order, "shipment": ship, "passport": self.passport(d.customer_id),
                "product_category": (order.items[0].get("category") if order and order.items else None) or "general",
                "shipping_method": (order.items[0].get("shipping") if order and order.items else None) or "standard",
                "account_age_days": int((self.now() - created) / DAY), "prior_orders": len(h["orders"]),
                "has_customer_correspondence": any(e.type == "ticket" for e in h["engagement"]),
                "transaction_at": None}

    def _on_dispute(self, d: Dispute, extra_ctx: dict | None = None) -> list[dict]:
        ctx = self._dispute_context(d)
        ctx.update(extra_ctx or {})
        payload = canonical_to_payload(d, ctx)
        analysis = analyse_dispute(payload)
        win_p = analysis.get("win_probability")
        pack = assemble_evidence_pack(payload, analysis["evidence"], analysis.get("response", {}).get("response_text"))
        cands, meta = dispute_candidates(d.amount, win_p, d.pre_dispute, self.policy, evidence_ok=pack["completeness"] >= 0.5)
        dl = deadline_status(d.respond_by, self.now())
        passport = ctx["passport"]
        case = Case("clawback", d.customer_id, d.amount, {"dispute_id": d.id, "customer_name": passport["profile"].get("name") or "there"},
                    passport, deadline=d.respond_by, kind="pre_dispute" if d.pre_dispute else "chargeback", must_act=True)
        rec = self._open_case(case, cands, {**meta, "deadline": dl, "existing_pipeline_action": analysis.get("response", {}).get("action")},
                              kind=case.kind, extra={"dispute": d, "payload": payload, "analysis": analysis, "evidence_pack": pack,
                                                     "deadline_status": dl})
        return [rec]

    def add_dispute(self, d: Dispute, ctx: dict | None = None) -> dict:
        """Register a dispute (e.g. from the console form) with explicit evidence context, then decide."""
        self.hist(d.customer_id)["disputes"].append(d)
        return self._on_dispute(d, ctx)[0]

    def evaluate_dispute_payload(self, payload: dict) -> dict:
        """Legacy DisputePayload shape -> canonical Dispute + evidence context, decided by the Kernel."""
        now = self.now()
        cust = payload.get("customer_id") or f"custom:{payload['dispute_id']}"
        d = Dispute(id=payload["dispute_id"], customer_id=self.resolver.canonical(cust), network=payload.get("card_network"),
                    amount=payload["dispute_amount"], opened_at=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                    respond_by=datetime.fromtimestamp(now + 10 * DAY, timezone.utc).isoformat(),
                    reason_code=payload.get("reason_code_label"), pre_dispute=bool(payload.get("pre_dispute")))
        ctx = {"delivered": payload.get("delivery_confirmed", False), "has_delivery_proof": payload.get("has_delivery_proof", False),
               "ip_geolocation_match": payload.get("ip_geolocation_match", False), "avs_cvv_match": payload.get("avs_cvv_match", "neither"),
               "has_3ds_authentication": payload.get("has_3ds_authentication", False),
               "account_age_days": payload.get("customer_account_age_days", 0), "prior_orders": payload.get("customer_prior_orders", 0),
               "has_customer_correspondence": payload.get("has_customer_correspondence", False),
               "product_category": payload.get("product_category", "general"), "shipping_method": payload.get("shipping_method", "standard"),
               "transaction_at": now - payload.get("days_to_dispute", 20) * DAY}
        self.hist(d.customer_id)
        return self.add_dispute(d, ctx)

    def _on_refund(self, r: Refund) -> list[dict]:
        h = self.hist(r.customer_id)
        order = h["orders"][-1] if h["orders"] else None
        ship = next((s for s in h["shipments"] if order and s.order_id == order.id), None)
        digital = bool(order and order.items and order.items[0].get("digital"))
        usage = sum(1 for e in h["engagement"] if e.type == "usage" and self.now() - ts(e.timestamp) <= 14 * DAY)
        reason = (r.reason or "other").lower().replace(" ", "_")
        req = {"amount": r.amount, "reason": reason, "delivered": bool(ship and ship.delivered_at), "has_pod": bool(ship and ship.pod),
               "days_since_delivery": int((self.now() - ts(ship.delivered_at)) / DAY) if ship and ship.delivered_at else 0,
               "digital": digital, "usage_events_after_delivery": usage}
        passport = self.passport(r.customer_id)
        cands, meta = refund_candidates(req, passport, self.policy)
        case = Case("refunds", r.customer_id, r.amount, {"refund_id": r.id, "reason": reason, "customer_name": passport["profile"].get("name") or "there",
                                                         "credit": r.amount * 1.1}, passport, kind="refund_request", must_act=True)
        rec = self._open_case(case, cands, {**meta, "request": req}, kind="refund_request", extra={"refund": r})
        return [rec] + self.evaluate_retention(r.customer_id)

    def _on_order(self, o: Order) -> list[dict]:
        h = self.hist(o.customer_id)
        hist = {"prior_orders": len(h["orders"]) - 1, "prior_rto": sum(1 for s in h["shipments"] if s.rto)}
        order = {"payment_mode": o.payment_mode, "pincode": o.pincode, "address": o.address, "amount": o.amount,
                 "new_device": False, "order_hour": datetime.fromtimestamp(ts(o.created_at, default=self.now()), timezone.utc).hour}
        cands, meta = rto_candidates(order, hist, self.policy)
        passport = self.passport(o.customer_id)
        case = Case("rto", o.customer_id, o.amount, {"order_id": o.id, "customer_name": passport["profile"].get("name") or "there"},
                    passport, kind="rto_risk", must_act=True)
        if o.payment_mode != "COD":
            case.features["prepaid"] = True
        return [self._open_case(case, cands, {**meta, "order": order}, kind="rto_risk", extra={"order": o})]

    # ── resolution & ledger ─────────────────────────────────────────────────
    def resolve_case(self, case_id: str, outcome: dict | None = None, advance: bool = True) -> dict:
        """Close a case and write the ledger. `outcome` = real result {success, recovered, cost}; omitted -> simulated."""
        rec = self.cases[case_id]
        if rec["status"] == "resolved":
            return rec
        if rec["status"] == "pending_approval":
            raise ValueError("case is awaiting approval")
        simulated = outcome is None
        out = outcome or self._simulate(rec)
        dec = rec["decision"]
        ch = dec["chosen"] or {}
        stake = rec["amount"]
        if rec["module"] == "clawback":
            stake = rec["amount"] + self.policy["dispute_fee_inr"] + self.policy["ratio_penalty_inr"]
        rec_out = {"success": bool(out.get("success")), "recovered": round(float(out.get("recovered", 0)), 2),
                   "cost": round(float(out.get("cost", ch.get("cost", 0))), 2), "simulated": simulated,
                   "source": out.get("source", "simulation" if simulated else "merchant"), "detail": out.get("detail")}
        rec["outcome"], rec["status"], rec["resolved_at"] = rec_out, "resolved", self.now()
        receipt = {"reason": dec["reason"], "rejected": dec["rejected"], "guardrails": dec["guardrails_triggered"],
                   "model_versions": dec["model_versions"], "policy_version": dec["policy_version"], "mode": dec["mode"],
                   "inputs": {k: v for k, v in rec["features"].items() if isinstance(v, (int, float, str, bool, type(None)))},
                   "outcome_simulated": simulated}
        if rec["module"] == "payments" and out.get("success") is not None and ch.get("action") == "schedule_retry" and rec["arm"] == "treatment":
            p = ch["params"]
            self.bandit.update(p["context"], p["arm"], bool(out.get("success")))
        if rec["module"] == "payments":
            self._payment_step_done(rec, ch, rec_out, receipt, advance)
        else:
            self.ledger.record(case_id=case_id, module=rec["module"], action=ch.get("action", "n/a"), amount_at_stake=stake,
                               recovered=rec_out["recovered"], cost=rec_out["cost"], arm=rec["arm"], customer_id=rec["customer_id"],
                               receipt=receipt, at=self.now())
        if rec.get("action_id") and rec["action_id"] in self.actions.records:
            self.actions.set_status(rec["action_id"], "completed")
        self.hist(rec["customer_id"])["actions"].append({"at": self.now(), "action": ch.get("action", "n/a"), "status": "completed"})
        self._emit("outcome.recorded", {"case_id": case_id, "module": rec["module"], "recovered": rec_out["recovered"], "arm": rec["arm"]})
        return rec

    def _payment_step_done(self, rec: dict, ch: dict, out: dict, receipt: dict, advance: bool):
        chain = rec["features"].get("chain")
        st = self.chains.get(chain)
        if not st:
            return
        a: PaymentAttempt = rec["attempt"]
        act = ch.get("action")
        st["cost"] += out["cost"]
        st["trail"].append({"step": rec["features"].get("step", 1), "action": act, "label": ch.get("label"),
                            "success": out["success"], "simulated": out["simulated"]})
        if out["success"]:
            return self._finalize_chain(chain, True, rec)
        if rec["arm"] == "holdout":
            return self._finalize_chain(chain, False, rec)
        if not advance:
            return None
        if act == "offer_pause":
            rng = random.Random(_h(rec["case_id"]) + 5)
            accepted = rng.random() < 0.32
            self.ledger.record(case_id=rec["case_id"] + ":save", module="retention", action="offer_pause",
                               amount_at_stake=ch.get("value", 0), recovered=ch.get("value", 0) if accepted else 0.0,
                               cost=ch.get("cost", 0), customer_id=rec["customer_id"], at=self.now(),
                               receipt={**receipt, "reason": ("Pause accepted: " if accepted else "Pause declined: ") + receipt["reason"]})
            st["trail"][-1]["pause_accepted"] = accepted
            return self._finalize_chain(chain, False, rec, pause=True)
        if st["steps"] >= 5:
            return self._finalize_chain(chain, False, rec)
        # the step failed: a failed retry is a new failed attempt; a failed link only raises the streak
        nxt = a.model_copy(update={"id": f"{a.id}_s{st['steps'] + 1}"})
        if act == "schedule_retry":
            nxt.attempted_at = ch["params"]["retry_at"]
            self.payment_index[nxt.id] = nxt.customer_id
            self.hist(nxt.customer_id)["attempts"].append(nxt)
        else:
            st["extra_streak"] += 1
        self._decide_payment(nxt, chain, st["root"], st["steps"] + 1)

    def _simulate(self, rec: dict) -> dict:
        """Outcome from the simulated world's ground truth (payments/disputes) or the model's own probability (others)."""
        rng = random.Random(_h(rec["case_id"]) + self.seed)
        ch = rec["decision"]["chosen"] or {}
        act, mod = ch.get("action"), rec["module"]
        if mod == "payments":
            a: PaymentAttempt = rec["attempt"]
            code, cat = a.decline_code or "other", a.decline_category or "soft"
            t0 = datetime.fromisoformat(a.attempted_at.replace("Z", "+00:00"))
            if rec["arm"] == "holdout":
                fail_all = 1.0
                for d in (1, 3, 5):
                    from datetime import timedelta
                    fail_all *= 1 - true_retry_p(code, t0, t0 + timedelta(days=d))
                ok = rng.random() > fail_all
                return {"success": ok, "recovered": a.amount if ok else 0.0, "cost": 0.0, "detail": "merchant's original retry logic"}
            if act == "schedule_retry":
                at = datetime.fromisoformat(ch["params"]["retry_at"])
                ok = rng.random() < true_retry_p(code, t0, at)
            elif act == "payment_update_link":
                ok = rng.random() < true_link_p(cat, 1.0)
            elif act == "upi_fallback":
                ok = rng.random() < 0.8 * true_link_p(cat, 1.0)
            else:
                ok = False
            if act == "offer_pause":
                return {"success": False, "recovered": 0.0, "cost": ch.get("cost", 0), "detail": "pause offered; retention case tracks the save"}
            return {"success": ok, "recovered": a.amount if ok else 0.0, "cost": ch.get("cost", 0)}
        if mod == "clawback":
            A = rec["amount"]
            if act == "submit_evidence":
                p = ch["params"]["win_probability"]
                won = rng.random() < p
                return {"success": won, "recovered": A + self.policy["dispute_fee_inr"] if won else 0.0,
                        "cost": self.policy["evidence_cost_inr"], "detail": "won" if won else "lost"}
            if act == "refund_early":
                return {"success": True, "recovered": self.policy["dispute_fee_inr"] + self.policy["ratio_penalty_inr"], "cost": 0.0,
                        "detail": "fee and ratio damage avoided"}
            return {"success": False, "recovered": 0.0, "cost": 0.0, "detail": "conceded"}
        if mod == "refunds":
            return {"success": ch.get("ev", 0) > 0, "recovered": max(0.0, ch.get("ev", 0)), "cost": ch.get("cost", 0),
                    "detail": "expected saving vs approving (sampled from model)"}
        ok = rng.random() < ch.get("p_success", 0)
        return {"success": ok, "recovered": ch.get("value", 0) if ok else 0.0, "cost": ch.get("cost", 0)}

    def simulate_pending(self, limit: int = 1000) -> int:
        """Resolve every active case with a simulated outcome, following recovery chains to their end (demo/backfill)."""
        n = 0
        for _ in range(6):
            todo = [cid for cid, r in self.cases.items() if r["status"] in ("active", "holdout")]
            if not todo or n >= limit:
                break
            for cid in todo[: limit - n]:
                self.resolve_case(cid)
                n += 1
        return n

    # ── views ───────────────────────────────────────────────────────────────
    def public_case(self, rec: dict, full: bool = False) -> dict:
        skip = {"_case", "_cands", "attempt", "dispute", "refund", "order", "payload", "analysis"}
        d = {k: v for k, v in rec.items() if k not in skip}
        if "analysis" in rec and full:
            a = rec["analysis"]
            d["analysis"] = {"classification": a.get("classification"), "win_probability": a.get("win_probability"),
                             "reasoning": a.get("reasoning"), "response_action": a.get("response", {}).get("action")}
        if full and rec["module"] == "payments" and "attempt" in rec:
            d["attempt"] = rec["attempt"].model_dump()
        d["action"] = self.actions.records.get(rec.get("action_id"))
        d["explain"] = rec["decision"]["reason"]
        return d

    def list_cases(self, module: str | None = None, status: str | None = None, customer: str | None = None) -> list[dict]:
        out = []
        for rec in sorted(self.cases.values(), key=lambda r: -r["created_at"]):
            if module and rec["module"] != module:
                continue
            if status and rec["status"] != status:
                continue
            if customer and self.resolver.canonical(rec["customer_id"]) != self.resolver.canonical(customer):
                continue
            out.append(self.public_case(rec))
        return out

    def customer_view(self, customer_id: str) -> dict:
        root = self.resolver.canonical(customer_id)
        if root not in self.history:
            raise KeyError(customer_id)
        return {"passport": self.passport(root), "identity": self.resolver.profile(root),
                "cases": self.list_cases(customer=root), "actions": [a for a in self.actions.records.values()
                                                                    if self.resolver.canonical(a["customer_id"]) == root][-10:]}

    def list_customers(self, sort: str = "exposure", limit: int = 100) -> list[dict]:
        rows = []
        for cid in list(self.history):
            p = self.passport(cid)
            rows.append({"customer_id": cid, "name": p["profile"].get("name") or cid, "email": p["profile"].get("email"),
                         "value_score": p["value_score"], "trust_score": p["trust_score"], "churn_risk": p["churn_risk"],
                         "churn_type": p["churn_type"], "payment_health": p["payment_health"]["score"],
                         "exposure": p["leak_exposure"]["total"], "serial_abuser": p["serial_abuser"], "fusion": bool(p["fusion"]),
                         "sources": sorted(p["profile"].get("source_ids", {}).keys())})
        key = {"exposure": lambda r: -r["exposure"], "churn": lambda r: -r["churn_risk"], "value": lambda r: -r["value_score"]}.get(sort, lambda r: -r["exposure"])
        return sorted(rows, key=key)[:limit]

    def overview(self) -> dict:
        now, since = self.now(), self.now() - 30 * DAY
        recent = [r for r in self.cases.values() if r["created_at"] >= since]
        leak = {k: {"at_stake": 0.0, "recovered": 0.0, "cases": 0, "open": 0} for k in ("failed", "clawed_back", "stopped", "missed")}
        for r in recent:
            if r["status"] == "no_action" and r["module"] in ("rto", "refunds"):
                continue
            leak[LEAK_OF[r["module"]]]["at_stake"] += r["amount"] if r["module"] != "rto" else r["amount"] * (r["meta"].get("rto_probability", 0))
            leak[LEAK_OF[r["module"]]]["cases"] += 1
            leak[LEAK_OF[r["module"]]]["open"] += r["status"] in ("active", "pending_approval", "recommended")
        for e in self.ledger.entries:
            if e["at"] >= since and e["arm"] == "treatment":
                leak[LEAK_OF[e["module"]]]["recovered"] += e["recovered"]
        bill = self.billing()
        leak["missed"]["at_stake"] += bill["assurance_total"]
        for k in leak:
            leak[k]["still_leaking"] = max(0.0, leak[k]["at_stake"] - leak[k]["recovered"])
            for f in ("at_stake", "recovered", "still_leaking"):
                leak[k][f] = round(leak[k][f], 2)
        total = sum(v["at_stake"] for v in leak.values())
        rec_total = sum(v["recovered"] for v in leak.values())
        weeks = []
        for w in range(7, -1, -1):
            lo, hi = now - (w + 1) * 7 * DAY, now - w * 7 * DAY
            weeks.append({"week": f"-{w}w" if w else "this wk",
                          "at_stake": round(sum(r["amount"] for r in self.cases.values() if lo <= r["created_at"] < hi and r["module"] in ("payments", "clawback", "retention")), 2),
                          "recovered": round(sum(e["recovered"] for e in self.ledger.entries if lo <= e["at"] < hi and e["arm"] == "treatment"), 2)})
        pend = [a for a in self.approvals.values() if a["status"] == "pending"]
        open_recs = [r for r in self.cases.values() if r["status"] in ("pending_approval", "recommended", "active")]
        top = sorted(open_recs, key=lambda r: -(r["decision"]["ev"] or 0))[:5]
        return {"headline": f"You are leaking ₹{total:,.0f} this month.", "leaking_30d": round(total, 2), "recovered_30d": round(rec_total, 2),
                "still_leaking": round(max(0.0, total - rec_total), 2), "by_leak": leak, "trend": weeks,
                "pending_approvals": len(pend), "customers": len(self.history), "cases": len(self.cases),
                "status_counts": {k: sum(1 for r in self.cases.values() if r["status"] == k) for k in ("active", "pending_approval", "recommended", "resolved", "no_action")},
                "top_actions": [{"case_id": r["case_id"], "module": r["module"], "action": (r["decision"]["chosen"] or {}).get("label"),
                                 "ev": r["decision"]["ev"], "amount": r["amount"], "status": r["status"], "reason": r["decision"]["reason"]} for r in top],
                "ledger": self.ledger.summary(), "chain": self.ledger.verify_chain()}

    # ── payments console ────────────────────────────────────────────────────
    def payments_console(self) -> dict:
        cases = [r for r in self.cases.values() if r["module"] == "payments"]
        cats, funnel = {}, {"failed": len(cases), "actioned": 0, "recovered": 0}
        for r in cases:
            cat = r["features"].get("decline_category") or "soft"
            c = cats.setdefault(cat, {"count": 0, "amount": 0.0})
            c["count"] += 1
            c["amount"] += r["amount"]
            if r["status"] in ("active", "resolved", "pending_approval"):
                funnel["actioned"] += 1
            if r["status"] == "resolved" and (r["outcome"] or {}).get("success"):
                funnel["recovered"] += 1
        summ = self.ledger.summary().get("by_module", {}).get("payments")
        atts = [a for h in self.history.values() for a in h["attempts"]]
        return {"queue": [self.public_case(r) for r in sorted(cases, key=lambda r: -r["created_at"])[:60]],
                "funnel": funnel, "decline_breakdown": {k: {"count": v["count"], "amount": round(v["amount"], 2)} for k, v in cats.items()},
                "heatmap": {code: self.bandit.heatmap(code) for code in ("insufficient_funds", "bank_downtime", "do_not_honor", "limit_exceeded")},
                "bandit_observations": self.bandit.observations(), "baseline_vs_impulse": summ,
                "predunning": predunning_targets([m for h in self.history.values() for m in h["methods"]],
                                                 [s for h in self.history.values() for s in h["subscriptions"]], self.dt())[:20],
                "routing": routing_advice(atts, min_n=8)}

    def retention_console(self) -> dict:
        rows = []
        for cid in self.history:
            p = self.passport(cid)
            if not p["signals"]["has_subscription"] and p["monthly_revenue"] == 0:
                continue
            pers = persuadability(p)
            rec = next((r for r in self.cases.values() if r["module"] == "retention" and self.resolver.canonical(r["customer_id"]) == cid
                        and r["status"] not in ("resolved", "rejected")), None)
            rows.append({"customer_id": cid, "name": p["profile"].get("name") or cid, "churn_risk": p["churn_risk"], "churn_type": p["churn_type"],
                         "reasons": p["churn_reasons"], "at_risk_inr": round(p["churn_risk"] * p["value_score"], 2), "ltv": p["value_score"],
                         "persuadability": pers, "action": (rec["decision"]["chosen"] or {}).get("label") if rec else None,
                         "status": rec["status"] if rec else None, "fusion": p["fusion"], "case_id": rec["case_id"] if rec else None})
        rows.sort(key=lambda r: -r["at_risk_inr"])
        used = self.kernel.ctx.spend.get("offers", 0)
        return {"at_risk": rows[:60], "offer_budget": {"limit": self.policy["budgets_inr_per_month"]["offers"], "used": round(used, 2)},
                "totals": {"at_risk_inr": round(sum(r["at_risk_inr"] for r in rows), 2), "customers_at_risk": sum(1 for r in rows if r["churn_risk"] >= 0.35)}}

    # ── billing ─────────────────────────────────────────────────────────────
    def billing(self) -> dict:
        if self._billing is None:
            d = demo_billing_data(today=self.dt().replace(hour=0, minute=0, second=0, microsecond=0))
            findings = run_assurance(d["contracts"], d["invoices"], d["usage"], d["seats"], d["credits"], d["payments"], d["today"])
            model = LatenessModel().fit(d["paid_history"])
            work = collections_worklist(d["open_invoices"], model, d["today"])
            self._billing = {"findings": findings, "worklist": work, "assurance_total": round(sum(f["amount"] for f in findings), 2),
                             "overdue_total": round(sum(w["amount"] for w in work), 2), "data": d, "model": model}
        b = self._billing
        return {"findings": b["findings"], "worklist": b["worklist"], "assurance_total": b["assurance_total"],
                "overdue_total": b["overdue_total"], "promises": self.promises.promises,
                "promise_reliability": self.promises.reliability(),
                "followups": self.promises.due_followups(b["data"]["today"]), "tier": "roadmap: demo on planted-error data"}
