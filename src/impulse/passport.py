"""Customer Revenue Passport: one record per customer, read and written by every module."""

import time
from datetime import datetime, timezone

from .retention import score_churn

DAY = 86400


def ts(value, default=None) -> float:
    """ISO string / epoch / datetime -> epoch seconds."""
    if value is None:
        return default if default is not None else time.time()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return default if default is not None else time.time()


def empty_history() -> dict:
    return {"attempts": [], "subscriptions": [], "invoices": [], "refunds": [], "disputes": [], "orders": [],
            "shipments": [], "engagement": [], "methods": [], "actions": [], "offers_taken": 0,
            "opted_out": False, "recovered_ids": set()}


def _monthly(sub) -> float:
    return sub.amount * {"monthly": 1, "yearly": 1 / 12, "weekly": 4.33}.get(sub.interval, 1) * max(sub.seats, 1) \
        if sub.status in ("active", "past_due", "paused") else 0.0


def churn_signals(hist: dict, now: float) -> dict:
    att = sorted(hist["attempts"], key=lambda a: ts(a.attempted_at))
    fails_30 = [a for a in att if a.status == "failed" and now - ts(a.attempted_at) <= 30 * DAY]
    streak = 0
    for a in reversed(att):
        if a.status == "failed":
            streak += 1
        else:
            break
    last_ok = max((ts(a.attempted_at) for a in att if a.status == "succeeded"), default=None)
    eng = hist["engagement"]
    recent = [e for e in eng if e.type == "usage" and now - ts(e.timestamp) <= 14 * DAY]
    prior = [e for e in eng if e.type == "usage" and 14 * DAY < now - ts(e.timestamp) <= 42 * DAY]
    prior_rate = sum(e.value for e in prior) / 28 if prior else None
    usage_decay = 0.0
    if prior_rate:
        usage_decay = max(0.0, 1 - (sum(e.value for e in recent) / 14) / prior_rate)
    tickets = sum(1 for e in eng if e.type == "ticket") - sum(1 for e in eng if e.type == "ticket_resolved")
    return {
        "failure_streak": streak,
        "failures_30d": len(fails_30),
        "days_since_last_success": round((now - last_ok) / DAY, 1) if last_ok else None,
        "usage_decay": round(usage_decay, 2),
        "unresolved_tickets": max(0, tickets),
        "downgrades": sum(1 for e in eng if e.type == "downgrade"),
        "seat_reductions": sum(1 for e in eng if e.type == "seat_reduction"),
        "has_subscription": any(s.status != "canceled" for s in hist["subscriptions"]),
    }


def build_passport(customer_id: str, profile: dict, hist: dict, now: float | None = None) -> dict:
    now = now or time.time()
    att = hist["attempts"]
    ok = [a for a in att if a.status == "succeeded"]
    failed = [a for a in att if a.status == "failed"]
    refunds = [r for r in hist["refunds"] if r.status != "declined"]
    disputes = hist["disputes"]
    rto = sum(1 for s in hist["shipments"] if s.rto)

    signals = churn_signals(hist, now)
    churn = score_churn(signals)

    monthly = sum(_monthly(s) for s in hist["subscriptions"])
    if not monthly and ok:
        span = max((now - min(ts(a.attempted_at) for a in ok)) / (30 * DAY), 1)
        monthly = sum(a.amount for a in ok) / span
    hazard = 0.02 + 0.25 * churn["score"]
    ltv = round(monthly * min(max(1 / hazard, 3), 30), 2)

    refund_rate = len(refunds) / max(len(ok), 1) if (ok or refunds) else 0.0
    lost_disputes = sum(1 for d in disputes if d.status in ("lost", "accepted"))
    trust = 100 - 35 * min(1, refund_rate * 2.5) - 18 * min(3, len(disputes)) - 10 * min(3, rto)
    trust = round(max(0, min(100, trust)), 1)
    serial = (len(refunds) >= 3 and refund_rate >= 0.4) or len(disputes) >= 2

    health = 100 - 22 * min(signals["failure_streak"], 4) - 6 * min(signals["failures_30d"], 5)
    unrecovered = [a for a in failed if a.id not in hist["recovered_ids"]]
    hard_seen = any(a.decline_category == "hard" for a in failed[-5:])
    exposure = {
        "failed": round(sum(a.amount for a in unrecovered if now - ts(a.attempted_at) <= 30 * DAY), 2),
        "clawed_back": round(sum(d.amount for d in disputes if d.status in ("open", "under_review"))
                             + sum(r.amount for r in hist["refunds"] if r.status == "requested"), 2),
        "stopped": round(churn["score"] * monthly * 3, 2),
        "missed": 0.0,
    }
    exposure["total"] = round(sum(exposure.values()), 2)

    timeline = []
    for a in att:
        timeline.append({"t": ts(a.attempted_at), "type": "payment_" + a.status, "gateway": a.gateway,
                         "detail": f"₹{a.amount:,.0f}" + (f" · {a.decline_code}" if a.decline_code else "")})
    for r in hist["refunds"]:
        timeline.append({"t": ts(r.requested_at), "type": "refund", "detail": f"₹{r.amount:,.0f} · {r.reason or 'n/a'}"})
    for d in disputes:
        timeline.append({"t": ts(d.opened_at), "type": "dispute", "detail": f"₹{d.amount:,.0f} · {d.reason_code or 'n/a'}"})
    for e in hist["engagement"]:
        if e.type not in ("usage", "login"):
            timeline.append({"t": ts(e.timestamp), "type": e.type, "detail": ""})
    for act in hist["actions"]:
        timeline.append({"t": act["at"], "type": "impulse_action", "detail": f"{act['action']} ({act['status']})"})
    timeline.sort(key=lambda x: -x["t"])

    passport = {
        "customer_id": customer_id,
        "profile": profile,
        "value_score": ltv,
        "monthly_revenue": round(monthly, 2),
        "trust_score": trust,
        "churn_risk": churn["score"],
        "churn_type": churn["type"],
        "churn_reasons": churn["reasons"],
        "payment_health": {"score": max(0, health), "failure_streak": signals["failure_streak"],
                           "failures_30d": signals["failures_30d"], "hard_decline_recent": hard_seen,
                           "methods": sorted({m.type for m in hist["methods"]}),
                           "recent_declines": [a.decline_code for a in failed[-3:]]},
        "clawback_history": {"refund_count": len(refunds), "refund_rate": round(refund_rate, 2),
                             "disputes": len(disputes), "disputes_lost": lost_disputes, "rto_events": rto},
        "leak_exposure": exposure,
        "active_actions": [a for a in hist["actions"] if a["status"] in ("executed", "pending_approval", "scheduled")][-6:],
        "serial_abuser": bool(serial),
        "offers_taken": hist["offers_taken"],
        "opted_out": hist["opted_out"],
        "timeline": timeline[:40],
        "signals": signals,
    }
    passport["fusion"] = detect_fusion(passport, hist, now)
    return passport


def detect_fusion(passport: dict, hist: dict, now: float) -> dict | None:
    """Multiple simultaneous leak signals become ONE compound, high-priority case."""
    win = 30 * DAY
    signals = []
    if any(a.status == "failed" and now - ts(a.attempted_at) <= win for a in hist["attempts"]):
        signals.append("payment_failure")
    if any(now - ts(r.requested_at) <= win for r in hist["refunds"]):
        signals.append("refund_request")
    if any(e.type == "ticket" and now - ts(e.timestamp) <= win for e in hist["engagement"]) and passport["signals"]["unresolved_tickets"]:
        signals.append("support_complaint")
    if any(now - ts(d.opened_at) <= win for d in hist["disputes"]):
        signals.append("dispute")
    if passport["signals"]["downgrades"] or passport["signals"]["seat_reductions"]:
        signals.append("downgrade")
    if len(signals) < 3:
        return None
    return {"signals": signals, "severity": "high", "exposure": passport["leak_exposure"]["total"],
            "recommendation": "personal_outreach",
            "explanation": f"{len(signals)} simultaneous signals ({', '.join(signals)}): treat as one relationship at risk, "
                           f"not {len(signals)} separate automated cases."}
