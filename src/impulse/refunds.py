"""Clawback Defense B: refund requests. Abuse score + decision options, informed by the Passport.

All ₹ assumptions are modelling defaults (see policy) and are labelled as such in the UI."""

import math

from .kernel import Candidate

REASONS = ("not_received", "not_as_described", "defective", "changed_mind", "duplicate_charge", "unauthorized", "other")


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def abuse_score(req: dict, passport: dict) -> dict:
    """P(this refund request is abusive). `req` keys: reason, delivered, has_pod, days_since_delivery,
    digital, usage_events_after_delivery, duplicate_verified. Returns score + top contributing factors."""
    reason = req.get("reason", "other")
    delivered, pod = bool(req.get("delivered")), bool(req.get("has_pod"))
    ch = passport.get("clawback_history", {})
    f = []  # (label, weight)
    f.append(("baseline", -2.2))
    if reason == "not_received" and delivered and pod:
        f.append(("claims 'not received' but delivery is proven (POD)", 2.8))
    elif reason == "not_received" and delivered:
        f.append(("claims 'not received' but carrier shows delivered", 1.2))
    if reason in ("not_as_described", "defective") and req.get("digital") and req.get("usage_events_after_delivery", 0) > 5:
        f.append(("digital product heavily used after claiming problem", 1.8))
    if reason == "unauthorized" and passport.get("profile", {}).get("email") and ch.get("refund_count", 0) >= 2:
        f.append(("'unauthorized' claim from a repeat refunder", 1.1))
    if reason == "duplicate_charge" and req.get("duplicate_verified"):
        f.append(("duplicate charge verified in gateway data", -2.5))
    if reason == "changed_mind":
        f.append(("change-of-mind is a policy question, not fraud", -0.4))
    rate = ch.get("refund_rate", 0)
    if rate > 0.2:
        f.append((f"refund rate {rate:.0%} of purchases", min(2.2, rate * 4)))
    if passport.get("serial_abuser"):
        f.append(("flagged serial refunder/disputer", 1.6))
    trust = passport.get("trust_score", 100)
    if trust < 60:
        f.append((f"low trust score ({trust:.0f})", (60 - trust) / 25))
    elif trust > 90 and not passport.get("serial_abuser"):
        f.append(("high trust history", -0.7))
    if req.get("days_since_delivery", 0) > 20:
        f.append(("request long after delivery", 0.7))
    z = sum(w for _, w in f)
    factors = sorted([{"factor": l, "weight": round(w, 2)} for l, w in f if l != "baseline"], key=lambda x: -abs(x["weight"]))
    return {"abuse_probability": round(_sigmoid(z), 3), "factors": factors[:4]}


def reason_is_duplicate(req: dict) -> bool:
    return req.get("reason") == "duplicate_charge"


def refund_candidates(req: dict, passport: dict, policy) -> tuple[list[Candidate], dict]:
    """Expected-utility comparison of the five options; every value is relative to simply approving."""
    A = float(req["amount"])
    L = max(passport.get("value_score", 0), 0.0)
    score = abuse_score(req, passport)
    pa = score["abuse_probability"]
    fee, ratio, ev_cost = policy["dispute_fee_inr"], policy["ratio_penalty_inr"], policy["evidence_cost_inr"]
    pw = 0.75 if req.get("has_pod") else 0.35            # win probability if the customer disputes anyway
    pd_abuser, pd_legit = 0.60, 0.45                      # chance of a dispute after a decline

    def dispute_loss(pd_):                                # expected ₹ loss of the dispute route
        return pd_ * ((1 - pw) * (A + fee) + ratio + ev_cost)

    # per-population utilities (₹, negative = cost)
    approve = {"abuser": -A, "legit": -A + 0.10 * L}
    decline = {"abuser": -dispute_loss(pd_abuser), "legit": -dispute_loss(pd_legit) - 0.35 * L}
    proof = {"abuser": 0.65 * 0.0 + 0.35 * approve["abuser"] - 40,
             "legit": 0.85 * (approve["legit"] - 0.03 * L) + 0.15 * decline["legit"] - 40}
    partial = {"abuser": 0.5 * (-0.5 * A) + 0.5 * decline["abuser"],
               "legit": 0.6 * (-0.5 * A - 0.05 * L) + 0.4 * approve["legit"]}
    credit_cost = 0.4 * A * 1.1                            # store credit costs COGS, not cash
    credit = {"abuser": 0.3 * (-credit_cost) + 0.7 * decline["abuser"],
              "legit": 0.7 * (-credit_cost + 0.08 * L) + 0.3 * approve["legit"]}

    def blend(u):
        return pa * u["abuser"] + (1 - pa) * u["legit"]

    base = blend(approve)
    opts = [("approve_refund", "Approve the refund", approve, "customer appears legitimate"),
            ("request_proof", "Request proof before deciding", proof, "abusers tend to drop out when asked for evidence"),
            ("partial_refund", "Offer a partial refund", partial, "splits the loss while keeping goodwill"),
            ("offer_replacement_credit", "Offer replacement or store credit", credit, "credit costs COGS, not cash"),
            ("decline_refund", "Decline the refund", decline, "abuse likely and evidence favours the merchant")]
    if req.get("duplicate_verified") and reason_is_duplicate(req):
        opts = opts[:1]                                     # a verified double charge must simply be refunded
    cands = [Candidate(a, lbl, p_success=1.0, value=blend(u) - base, category="commercial" if a != "approve_refund" else "payment",
                       channel="email" if a != "approve_refund" else None, note=note,
                       params={"utility_inr": round(blend(u), 2)}) for a, lbl, u, note in opts]
    return cands, {**score, "assumptions": {"win_if_disputed": pw, "dispute_fee": fee}, "baseline_cost_inr": round(-base, 2)}
