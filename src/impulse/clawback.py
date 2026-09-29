"""Clawback Defense A: chargebacks on the canonical Dispute schema.

Wraps the existing, tested ChargebackResponder (classifier + evidence + win model) and adds:
canonical-schema mapping, evidence-pack assembly, deadline tracking and refund-vs-fight arbitrage.
"""

import os
import time
from datetime import datetime, timezone

from .kernel import Candidate
from .passport import ts

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_responder = None
_responder_error = None

NETWORK_MAP = {"visa": "Visa", "mastercard": "Mastercard", "mc": "Mastercard", "rupay": "Visa", "amex": "Visa"}

EVIDENCE_LABELS = {
    "has_delivery_proof": ("Delivery proof (carrier POD / signature)", "shipment.pod"),
    "delivery_confirmed": ("Delivery confirmed by carrier", "shipment.delivered_at"),
    "ip_geolocation_match": ("IP geolocation matches billing region", "order.device_ip"),
    "avs_cvv_match": ("AVS and CVV both matched", "payment.avs_cvv"),
    "has_3ds_authentication": ("3-D Secure authentication passed", "payment.3ds"),
    "has_customer_correspondence": ("Customer correspondence / support thread", "engagement.ticket"),
}


def get_responder():
    """Lazy singleton so the pkl models load once per process."""
    global _responder, _responder_error
    if _responder is None and _responder_error is None:
        try:
            from src.pipeline.run import ChargebackResponder
            _responder = ChargebackResponder(os.path.join(_PROJECT_ROOT, "models", "classifier.pkl"),
                                             os.path.join(_PROJECT_ROOT, "models", "win_predictor.pkl"))
        except Exception as exc:  # models missing on a fresh checkout
            _responder_error = str(exc)
    return _responder


def canonical_to_payload(dispute, ctx: dict | None = None) -> dict:
    """Canonical Dispute (+ order/shipment/passport context) -> the existing pipeline's input."""
    ctx = ctx or {}
    order, ship, passport = ctx.get("order"), ctx.get("shipment"), ctx.get("passport", {})
    opened = ts(dispute.opened_at)
    tx = ts(ctx.get("transaction_at"), default=opened - 20 * 86400)
    ch = passport.get("clawback_history", {})
    delivered = bool(ship and ship.delivered_at) or ctx.get("delivered", False)
    return {
        "dispute_id": dispute.id,
        "card_network": NETWORK_MAP.get((dispute.network or "visa").lower(), "Visa"),
        "dispute_amount": float(dispute.amount),
        "currency": "INR",
        "transaction_date": datetime.fromtimestamp(tx, timezone.utc).date().isoformat(),
        "days_to_dispute": max(0, int((opened - tx) / 86400)),
        "product_category": ctx.get("product_category", "general"),
        "shipping_method": ctx.get("shipping_method", "standard"),
        "delivery_confirmed": delivered,
        "has_delivery_proof": bool(ship and ship.pod) or ctx.get("has_delivery_proof", False),
        "ip_geolocation_match": ctx.get("ip_geolocation_match", False),
        "avs_cvv_match": ctx.get("avs_cvv_match", "neither"),
        "customer_account_age_days": int(ctx.get("account_age_days", 0)),
        "customer_prior_disputes": ch.get("disputes", 0),
        "customer_prior_orders": int(ctx.get("prior_orders", 0)),
        "has_customer_correspondence": ctx.get("has_customer_correspondence", False),
        "has_3ds_authentication": ctx.get("has_3ds_authentication", False),
        "reason_code_label": dispute.reason_code,
    }


def deadline_status(respond_by, now: float | None = None) -> dict:
    """respond_by tracking with alert levels."""
    now = now or time.time()
    if not respond_by:
        return {"hours_left": None, "urgency": "unknown", "alert": "No respond-by date on this dispute."}
    hrs = (ts(respond_by) - now) / 3600
    if hrs < 0:
        return {"hours_left": round(hrs, 1), "urgency": "overdue", "alert": "Deadline passed: automatic loss."}
    if hrs < 24:
        return {"hours_left": round(hrs, 1), "urgency": "critical", "alert": f"Respond within {hrs:.0f}h."}
    if hrs < 72:
        return {"hours_left": round(hrs, 1), "urgency": "high", "alert": f"{hrs / 24:.1f} days left."}
    return {"hours_left": round(hrs, 1), "urgency": "normal", "alert": f"{hrs / 24:.0f} days left."}


def assemble_evidence_pack(payload: dict, evidence: dict, response_text: str | None = None) -> dict:
    """Auto-assemble the representment pack: what we have, where it came from, what's missing."""
    pkg = evidence["evidence_package"]
    have = {e["field"] for e in pkg["compelling"]} | {e["field"] for e in pkg["supporting"]}
    items = []
    for field, (label, source) in EVIDENCE_LABELS.items():
        val = payload.get(field)
        present = field in have or (field == "avs_cvv_match" and val == "both_match")
        role = "compelling" if field in {e["field"] for e in pkg["compelling"]} or field in pkg["missing"] else \
            ("supporting" if field in {e["field"] for e in pkg["supporting"]} else "not_required")
        items.append({"field": field, "label": label, "source_system": source, "present": bool(present), "role": role})
    required = [i for i in items if i["role"] in ("compelling", "supporting") or i["field"] in pkg["missing"]]
    return {"items": items, "completeness": evidence["evidence_strength"],
            "missing": pkg["missing"], "required_count": len(required),
            "ready_to_submit": evidence["auto_respond_eligible"], "representment_text": response_text}


def dispute_candidates(amount: float, win_prob: float | None, pre_dispute: bool, policy,
                       evidence_ok: bool = True) -> tuple[list[Candidate], dict]:
    """Fight vs accept vs refund-early, as absolute ₹ cash outcomes converted to gain vs the worst option.

    cash(accept)      = -(A + fee + ratio)
    cash(fight)       = -ratio - evidence - (1 - p_win) x (A + fee)
    cash(refund_early)= -A       (only before the dispute is filed: no fee, no ratio damage)
    """
    A = float(amount)
    fee, ratio, evc = policy["dispute_fee_inr"], policy["ratio_penalty_inr"], policy["evidence_cost_inr"]
    p = win_prob if win_prob is not None else 0.35
    accept = -(A + fee + ratio)
    fight = -ratio - evc - (1 - p) * (A + fee)
    cash = {"accept": accept, "fight": fight}
    cands = [Candidate("accept_liability", "Accept liability", p_success=1.0, value=0.0, category="dispute",
                       note="concede; lose the amount, fee and ratio damage")]
    cands.append(Candidate("submit_evidence", f"Fight with evidence (win probability {p:.0%})", p_success=1.0,
                           value=fight - accept, category="dispute",
                           params={"win_probability": round(p, 4)},
                           note="evidence pack ready" if evidence_ok else "evidence is thin: lower odds already priced in"))
    if pre_dispute:
        cash["refund_early"] = -A
        cands.append(Candidate("refund_early", "Refund now, before it becomes a dispute", p_success=1.0,
                               value=-A - accept, category="payment",
                               note=f"avoids the ₹{fee:,.0f} fee and chargeback-ratio damage"))
    return cands, {"cash_outcomes_inr": {k: round(v, 2) for k, v in cash.items()}, "win_probability": p,
                   "win_model": "used" if win_prob is not None else "unavailable: neutral prior 35% assumed"}


def analyse_dispute(payload: dict) -> dict:
    """Run the existing pipeline (classifier, evidence, win model). Returns its result dict, or a degraded stub."""
    resp = get_responder()
    if resp is None:
        return {"degraded": True, "error": _responder_error, "win_probability": None,
                "classification": {"predicted_reason_code": None, "confidence": 0},
                "evidence": {"evidence_package": {"compelling": [], "supporting": [], "missing": []},
                             "evidence_strength": 0, "auto_respond_eligible": False},
                "response": {"action": "HUMAN_REVIEW", "response_text": ""}, "reasoning": ["Models unavailable."]}
    return resp.process(payload)
