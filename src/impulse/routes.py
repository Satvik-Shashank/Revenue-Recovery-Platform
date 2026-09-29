"""FastAPI router: every Impulse screen and the public REST API. Mounted at /api/impulse by api/index.py."""

import io
import json
import os
import threading
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import audit as audit_mod
from . import narrative
from .demo import refill_samples, sample_events, seed_demo, try_payment
from .engine import ImpulseEngine
from .ingest import compute_signature
from .sim import cached_replay, run_replay

router = APIRouter(prefix="/api/impulse", tags=["impulse"])

_lock = threading.Lock()
_state: dict = {"engine": None, "scenarios": None}


def engine() -> ImpulseEngine:
    """Lazily seed the deterministic demo world once per process."""
    if _state["engine"] is None:
        with _lock:
            if _state["engine"] is None:
                if os.getenv("IMPULSE_EMPTY") == "1":
                    _state["engine"], _state["scenarios"] = ImpulseEngine(), {}
                else:
                    _state["engine"], _state["scenarios"] = seed_demo()
    return _state["engine"]


def reset_engine(empty: bool = False):
    with _lock:
        _state["engine"], _state["scenarios"] = (ImpulseEngine(), {}) if empty else seed_demo()
    return _state["engine"]


def _nf(fn, *a, **k):
    try:
        return fn(*a, **k)
    except KeyError as exc:
        raise HTTPException(404, f"not found: {exc.args[0]}")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ── cockpit & meta ───────────────────────────────────────────────────────────

@router.get("/overview")
def overview():
    return engine().overview()


@router.get("/scenarios")
def scenarios():
    engine()
    return {"scenarios": _state["scenarios"], "note": "case ids / customer ids of the scripted showcase cases"}


@router.post("/reset")
def reset(empty: bool = False):
    reset_engine(empty)
    return {"status": "reset", "empty": empty}


@router.post("/samples/refill")
def samples_refill(count: int = Query(4, ge=1, le=8)):
    """Demo helper: add fresh decisions that need approval."""
    added = refill_samples(engine(), count)
    engine().audit("demo", "samples_refilled", {"added": added})
    return {"added": added}


class TryPayment(BaseModel):
    reason: str = "insufficient_funds"
    amount: float = Field(1299, gt=0, le=1_000_000)
    recurring: bool = True
    prior_failures: int = Field(0, ge=0, le=5)


@router.post("/try/payment")
def try_payment_route(body: TryPayment):
    """Playground: fail one payment for a fresh sample customer and return what Impulse decides."""
    e = engine()
    rec = try_payment(e, body.reason, body.amount, body.recurring, body.prior_failures)
    out = e.public_case(rec, full=True)
    out["explain"] = rec["decision"]["reason"]
    return out


class TryBilling(BaseModel):
    contract_price: float = Field(50000, ge=0)
    billed: float = Field(50000, ge=0)
    active_seats: int = Field(10, ge=0)
    billed_seats: int = Field(10, ge=0)
    seat_price: float = Field(1000, ge=0)
    used_units: int = Field(0, ge=0)
    included_units: int = Field(0, ge=0)
    unit_rate: float = Field(0, ge=0)
    invoiced: bool = True


@router.post("/billing/check")
def billing_check(b: TryBilling):
    """Playground: run the revenue-assurance checks on one hypothetical contract."""
    from datetime import datetime, timezone
    from .billing import run_assurance
    today = datetime.now(timezone.utc)
    contracts = [{"id": "CT-TRY", "customer": "Your customer", "price": b.contract_price, "cycles_due": 1}]
    invoices = [{"id": "INV-TRY", "contract_id": "CT-TRY", "customer": "Your customer", "amount": b.billed, "date": today.isoformat()[:10], "due_date": today.isoformat()[:10], "status": "open"}] if b.invoiced else []
    usage = [{"customer": "Your customer", "contract": "CT-TRY", "used_units": b.used_units, "included_units": b.included_units, "billed_overage_units": 0, "rate": b.unit_rate}] if b.used_units else []
    seats = [{"customer": "Your customer", "contract": "CT-TRY", "active_seats": b.active_seats, "billed_seats": b.billed_seats, "seat_price": b.seat_price}]
    findings = run_assurance(contracts, invoices, usage, seats, [], [], today)
    return {"findings": findings, "total": round(sum(f["amount"] for f in findings), 2)}


@router.get("/health")
def health():
    e = engine()
    return {"status": "ok", "customers": len(e.history), "cases": len(e.cases), "ledger_entries": len(e.ledger.entries),
            "llm": narrative.llm_available(), "persistence": "in_memory_demo_state"}


# ── ingestion & connections ──────────────────────────────────────────────────

class SimulateBody(BaseModel):
    name: str
    signed: bool = False


@router.get("/webhooks/samples")
def webhook_samples():
    return {k: {"source": v["source"], "label": v["label"]} for k, v in sample_events().items()}


@router.post("/webhooks/simulate")
def webhook_simulate(body: SimulateBody):
    ev = sample_events().get(body.name)
    if not ev:
        raise HTTPException(404, "unknown sample")
    raw = json.dumps(ev["event"]).encode()
    sig = None
    e = engine()
    secret = e.hub.secrets.get(ev["source"])
    if body.signed and secret:
        sig = compute_signature(secret, raw)
    res = e.ingest(ev["source"], raw, sig)
    cust = None
    if res.get("customer_ids"):
        try:
            v = e.customer_view(res["customer_ids"][0])
            cust = {"identity": v["identity"], "churn_risk": v["passport"]["churn_risk"], "trust_score": v["passport"]["trust_score"]}
        except KeyError:
            pass
    return {"sent": ev["label"], "payload": ev["event"], "result": res, "customer": cust,
            "cases": [e.public_case(e.cases[c]) for c in res.get("cases", []) if c in e.cases]}


@router.post("/webhooks/{source}")
async def webhook(source: str, request: Request):
    body = await request.body()
    sig = request.headers.get("x-razorpay-signature") or request.headers.get("stripe-signature") or request.headers.get("x-impulse-signature")
    res = engine().ingest(source, body, sig)
    if res["status"] == "rejected":
        raise HTTPException(401, res.get("reason", "rejected"))
    return res


@router.get("/connections")
def connections():
    e = engine()
    return {"connections": e.hub.connection_health(), "stats": e.hub.stats, "dead_letters": len(e.hub.dead_letters),
            "webhook_urls": e.webhook_urls, "endpoints": {s: f"/api/impulse/webhooks/{s}" for s in ("razorpay", "stripe", "custom")}}


class SecretBody(BaseModel):
    source: str
    secret: str | None = None


@router.put("/connections/secret")
def set_secret(body: SecretBody):
    e = engine()
    if body.secret:
        e.hub.secrets[body.source] = body.secret
    else:
        e.hub.secrets.pop(body.source, None)
    e.audit("merchant", "connection_secret_updated", {"source": body.source, "enabled": bool(body.secret)})
    return {"source": body.source, "signature_verification": bool(body.secret)}


@router.get("/dead-letters")
def dead_letters():
    return {"items": sorted(engine().hub.dead_letters.values(), key=lambda d: -d["at"])}


class ReplayBody(BaseModel):
    patched_event: dict | None = None


@router.post("/dead-letters/{dl_id}/replay")
def replay(dl_id: str, body: ReplayBody | None = None):
    return _nf(engine().replay_dead_letter, dl_id, body.patched_event if body else None)


@router.post("/events")
async def push_event(request: Request):
    """Public API: push a custom canonical event ({"entity": "engagement", ...})."""
    return engine().ingest("custom", await request.body())


class WebhookUrl(BaseModel):
    url: str = Field(..., pattern=r"^https?://")


@router.post("/outbound-webhooks")
def add_outbound(body: WebhookUrl):
    e = engine()
    if body.url not in e.webhook_urls:
        e.webhook_urls.append(body.url)
    return {"webhook_urls": e.webhook_urls}


@router.delete("/outbound-webhooks")
def clear_outbound():
    engine().webhook_urls.clear()
    return {"webhook_urls": []}


@router.get("/outbox")
def outbox(limit: int = Query(50, le=500)):
    return {"items": list(reversed(engine().outbox))[:limit]}


@router.get("/audit-log")
def audit_log(limit: int = Query(100, le=1000)):
    return {"items": list(reversed(engine().audit_log))[:limit]}


# ── identity ─────────────────────────────────────────────────────────────────

@router.get("/identity")
def identity():
    r = engine().resolver
    return {"merges": r.audit[-50:], "suggestions": r.suggestions[:30]}


class MergeBody(BaseModel):
    a: str
    b: str


@router.post("/identity/merge")
def identity_merge(body: MergeBody):
    e = engine()
    keep = _nf(e.resolver.merge, body.a, body.b)
    e._consolidate()
    return {"kept": keep}


@router.post("/identity/unmerge/{merge_id}")
def identity_unmerge(merge_id: str):
    return _nf(engine().resolver.unmerge, merge_id)


# ── customers ────────────────────────────────────────────────────────────────

@router.get("/customers")
def customers(sort: str = "exposure", limit: int = Query(100, le=500)):
    return {"customers": engine().list_customers(sort, limit)}


@router.post("/customers/{customer_id:path}/evaluate")
def evaluate_customer(customer_id: str):
    """Ask Impulse for a retention recommendation for one customer right now."""
    e = engine()
    root = e.resolver.canonical(customer_id)
    if root not in e.history:
        raise HTTPException(404, f"not found: {customer_id}")
    recs = e.evaluate_retention(root)
    if not recs:
        recs = [r for r in e.cases.values() if r["module"] == "retention" and e.resolver.canonical(r["customer_id"]) == root
                and r["status"] in ("active", "pending_approval", "recommended")]
    if not recs:
        raise HTTPException(400, "No action is needed for this customer right now.")
    return {"case_id": recs[0]["case_id"]}


@router.get("/customers/{customer_id:path}")
def customer(customer_id: str):
    return _nf(engine().customer_view, customer_id)


# ── modules ──────────────────────────────────────────────────────────────────

@router.get("/payments")
def payments():
    return engine().payments_console()


@router.get("/retention")
def retention():
    return engine().retention_console()


@router.get("/clawback")
def clawback():
    e = engine()
    disputes = [e.public_case(r, full=True) | {"deadline_status": r.get("deadline_status"), "evidence_pack": r.get("evidence_pack")}
                for r in sorted((r for r in e.cases.values() if r["module"] == "clawback"), key=lambda r: -r["created_at"])[:40]]
    refunds = e.list_cases(module="refunds")[:40]
    rto = e.list_cases(module="rto")[:40]
    summ = e.ledger.summary()["by_module"]
    return {"disputes": disputes, "refunds": refunds, "rto": rto, "summary": {k: summ.get(k) for k in ("clawback", "refunds", "rto")}}


@router.get("/cases")
def cases(module: str | None = None, status: str | None = None, customer: str | None = None, limit: int = Query(100, le=500)):
    return {"cases": engine().list_cases(module, status, customer)[:limit]}


@router.get("/cases/{case_id}")
def case(case_id: str):
    e = engine()
    rec = e.cases.get(case_id)
    if not rec:
        raise HTTPException(404, "case not found")
    out = e.public_case(rec, full=True)
    out["evidence_pack"] = rec.get("evidence_pack")
    out["deadline_status"] = rec.get("deadline_status")
    return out


class OutcomeBody(BaseModel):
    success: bool | None = None
    recovered: float | None = None
    cost: float | None = None
    simulate: bool = False


@router.post("/cases/{case_id}/resolve")
def resolve(case_id: str, body: OutcomeBody):
    e = engine()
    if body.simulate or body.success is None:
        return e.public_case(_nf(e.resolve_case, case_id))
    return e.public_case(_nf(e.resolve_case, case_id, {"success": body.success, "recovered": body.recovered or 0, "cost": body.cost or 0, "source": "merchant"}))


@router.post("/simulate/resolve-pending")
def resolve_pending(limit: int = 200):
    return {"resolved": engine().simulate_pending(limit)}


class DisputeIn(BaseModel):
    dispute_id: str
    card_network: str = "Visa"
    dispute_amount: float
    days_to_dispute: int = 20
    product_category: str = "general"
    shipping_method: str = "standard"
    delivery_confirmed: bool = False
    has_delivery_proof: bool = False
    ip_geolocation_match: bool = False
    avs_cvv_match: str = "neither"
    customer_account_age_days: int = 0
    customer_prior_disputes: int = 0
    customer_prior_orders: int = 0
    has_customer_correspondence: bool = False
    has_3ds_authentication: bool = False
    reason_code_label: str | None = None
    pre_dispute: bool = False


@router.post("/clawback/disputes")
def evaluate_dispute(body: DisputeIn):
    e = engine()
    rec = _nf(e.evaluate_dispute_payload, body.model_dump())
    out = e.public_case(rec, full=True)
    out["evidence_pack"], out["deadline_status"] = rec.get("evidence_pack"), rec.get("deadline_status")
    out["narrative"] = narrative.evidence_narrative(rec["payload"], rec["analysis"], rec["evidence_pack"])
    return out


@router.get("/cases/{case_id}/narrative")
def case_narrative(case_id: str):
    rec = engine().cases.get(case_id)
    if not rec or "analysis" not in rec:
        raise HTTPException(404, "no evidence narrative for this case")
    return narrative.evidence_narrative(rec["payload"], rec["analysis"], rec["evidence_pack"])


class RefundIn(BaseModel):
    customer_id: str
    amount: float
    reason: str = "not received"


@router.post("/clawback/refunds")
def score_refund(body: RefundIn):
    from .schema import Refund
    e = engine()
    if e.resolver.canonical(body.customer_id) not in e.history:
        raise HTTPException(404, "unknown customer")
    r = Refund(id=f"rf_api_{len(e.cases)}", customer_id=e.resolver.canonical(body.customer_id), amount=body.amount, reason=body.reason,
               requested_at=datetime.now(timezone.utc).isoformat())
    e.hist(r.customer_id)["refunds"].append(r)
    return e.public_case(e._on_refund(r)[0])


class OrderIn(BaseModel):
    customer_id: str
    amount: float
    payment_mode: str = "COD"
    pincode: str | None = None
    address: str | None = None


@router.post("/clawback/orders")
def score_order(body: OrderIn):
    from .schema import Order
    e = engine()
    if e.resolver.canonical(body.customer_id) not in e.history:
        raise HTTPException(404, "unknown customer")
    o = Order(id=f"ord_api_{len(e.cases)}", customer_id=e.resolver.canonical(body.customer_id), amount=body.amount, payment_mode=body.payment_mode,
              pincode=body.pincode, address=body.address, created_at=datetime.now(timezone.utc).isoformat())
    e.order_index[o.id] = o.customer_id
    e.hist(o.customer_id)["orders"].append(o)
    return e.public_case(e._on_order(o)[0])


@router.get("/billing")
def billing():
    return engine().billing()


class PromiseIn(BaseModel):
    invoice: str
    customer: str
    amount: float
    promised_date: str


@router.post("/billing/promises")
def add_promise(body: PromiseIn):
    return engine().promises.log(body.invoice, body.customer, body.amount, body.promised_date)


@router.post("/billing/promises/{pid}/{outcome}")
def mark_promise(pid: str, outcome: str):
    if outcome not in ("kept", "broken"):
        raise HTTPException(400, "outcome must be kept or broken")
    return _nf(engine().promises.mark, pid, outcome == "kept")


# ── approvals ────────────────────────────────────────────────────────────────

@router.get("/approvals")
def approvals(status: str | None = "pending"):
    items = [a for a in engine().approvals.values() if status in (None, "all", a["status"])]
    return {"items": sorted(items, key=lambda a: -a["ev"]), "pending": sum(1 for a in engine().approvals.values() if a["status"] == "pending")}


class ApprovalBody(BaseModel):
    verdict: str
    edit_action: str | None = None
    actor: str = "merchant"


@router.post("/approvals/{approval_id}")
def decide(approval_id: str, body: ApprovalBody):
    e = engine()
    return _nf(e.decide_approval, approval_id, body.verdict, body.edit_action, body.actor)


@router.post("/actions/{action_id}/undo")
def undo(action_id: str):
    e = engine()
    rec = _nf(e.actions.undo, action_id)
    e.audit("merchant", "action_undone", {"action": action_id})
    return rec


# ── ledger & policy ──────────────────────────────────────────────────────────

@router.get("/ledger")
def ledger(limit: int = Query(100, le=1000)):
    e = engine()
    return {"summary": e.ledger.summary(), "by_action": e.ledger.by_action(), "chain": e.ledger.verify_chain(),
            "entries": list(reversed(e.ledger.entries))[:limit]}


@router.get("/ledger/export.csv", response_class=PlainTextResponse)
def ledger_csv():
    return PlainTextResponse(engine().ledger.to_csv(), media_type="text/csv",
                             headers={"content-disposition": "attachment; filename=impulse-outcome-ledger.csv"})


@router.get("/ledger/verify")
def ledger_verify():
    return engine().ledger.verify_chain()


@router.get("/policy")
def get_policy():
    return engine().policy.data


@router.put("/policy")
async def put_policy(request: Request):
    e = engine()
    patch = await request.json()
    try:
        data = e.policy.update(patch)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    e.ledger.fee_pct = data["fee_pct"]
    e.audit("merchant", "policy_updated", {"patch": patch, "version": data["version"]})
    return data


class AskBody(BaseModel):
    question: str = Field(..., max_length=300)


@router.post("/ask")
def ask(body: AskBody):
    e = engine()
    return narrative.answer_question(body.question, e.ledger, e)


# ── Replay Lab ───────────────────────────────────────────────────────────────

@router.get("/replay-lab")
def replay_lab():
    return cached_replay()


@router.post("/replay-lab/run")
def replay_lab_run(cases: int = Query(400, ge=100, le=1500), worlds: int = Query(3, ge=1, le=6), holdout_pct: float = Query(10, ge=0, le=40)):
    return run_replay(n=cases, seeds=worlds, holdout_pct=holdout_pct)


# ── Leak Audit ───────────────────────────────────────────────────────────────

_audit_sessions: dict[str, dict] = {}


def _read(upload: UploadFile) -> pd.DataFrame:
    raw = upload.file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "file over 10MB")
    name = (upload.filename or "").lower()
    try:
        return pd.read_excel(io.BytesIO(raw)) if name.endswith((".xlsx", ".xls")) else pd.read_csv(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(400, f"could not read {upload.filename}: {exc}")


@router.post("/audit/upload")
async def audit_upload(payments: UploadFile | None = File(None), disputes: UploadFile | None = File(None), refunds: UploadFile | None = File(None),
                       subscriptions: UploadFile | None = File(None), invoices: UploadFile | None = File(None),
                       mappings: str = Form("{}")):
    frames = {k: _read(v) for k, v in (("payments", payments), ("disputes", disputes), ("refunds", refunds),
                                       ("subscriptions", subscriptions), ("invoices", invoices)) if v is not None}
    if not frames:
        raise HTTPException(400, "upload at least one file")
    try:
        maps = json.loads(mappings or "{}")
    except ValueError:
        raise HTTPException(400, "mappings must be JSON")
    previews = {k: {"columns": list(df.columns), "suggested": {f: v for f, v in audit_mod.auto_map(df, k).items()}, "rows": int(len(df))}
                for k, df in frames.items() if k in audit_mod.KINDS}
    report = audit_mod.run_audit(frames, maps)
    sid = f"aud_{len(_audit_sessions) + 1}"
    _audit_sessions[sid] = report
    return {"session": sid, "report": report, "previews": previews}


@router.get("/audit/sample")
def audit_sample():
    report = audit_mod.run_audit(audit_mod.sample_audit_data())
    sid = f"aud_{len(_audit_sessions) + 1}"
    _audit_sessions[sid] = report
    return {"session": sid, "report": report, "sample": True}


@router.get("/audit/{sid}/report", response_class=HTMLResponse)
def audit_report(sid: str, merchant: str = "Your business"):
    rep = _audit_sessions.get(sid)
    if not rep:
        raise HTTPException(404, "audit session not found (sessions live in memory)")
    return HTMLResponse(audit_mod.render_report_html(rep, merchant))


# ── customer-facing hosted pages (simulated) ─────────────────────────────────

class HostedAction(BaseModel):
    choice: str
    otp: str | None = None


@router.get("/hosted/{case_id}")
def hosted_view(case_id: str):
    e = engine()
    rec = e.cases.get(case_id)
    if not rec:
        raise HTTPException(404, "link expired or invalid")
    ch = rec["decision"]["chosen"] or {}
    name = (rec["features"].get("customer_name") or "there")
    return {"case_id": case_id, "customer_name": name, "amount": rec["amount"], "module": rec["module"], "action": ch.get("action"),
            "page": {"payment_update_link": "payment_update", "upi_fallback": "payment_update", "offer_pause": "pause_or_downgrade",
                     "offer_downgrade": "pause_or_downgrade", "otp_verify": "otp", "prepaid_nudge": "payment_update"}.get(ch.get("action"), "payment_update"),
            "incentive": (ch.get("params") or {}).get("incentive_inr")}


@router.post("/hosted/{case_id}")
def hosted_act(case_id: str, body: HostedAction):
    e = engine()
    rec = e.cases.get(case_id)
    if not rec:
        raise HTTPException(404, "link expired or invalid")
    if rec["status"] == "resolved":
        return {"status": "already_completed"}
    if rec["status"] == "pending_approval":
        raise HTTPException(409, "not active yet")
    if body.choice == "otp" and body.otp not in ("123456",):
        raise HTTPException(400, "incorrect OTP (demo OTP is 123456)")
    a = rec.get("attempt")
    recovered = a.amount if a is not None and body.choice in ("pay_upi", "pay_card") else 0.0
    ok = body.choice in ("pay_upi", "pay_card", "pause", "downgrade", "otp", "prepaid")
    e.resolve_case(case_id, {"success": ok, "recovered": recovered if rec["module"] == "payments" else (rec["decision"]["chosen"] or {}).get("value", 0) * 0.5 if ok else 0,
                             "source": "customer_hosted_page", "detail": body.choice})
    return {"status": "completed", "choice": body.choice}
