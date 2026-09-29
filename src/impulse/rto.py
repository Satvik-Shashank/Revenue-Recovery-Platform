"""Clawback Defense C (Tier 2): COD returns / RTO. Order-time risk score + interventions.

Pincode risk here is a synthetic lookup (assumption): replace with the merchant's own pincode history."""

import math
import re

from .kernel import Candidate

HIGH_RISK_PREFIXES = {"11": 0.25, "70": 0.10, "80": 0.30, "78": 0.35, "19": 0.30, "40": 0.05, "56": 0.03, "60": 0.06}
ROUND_TRIP_SHIPPING_INR = 140
HANDLING_INR = 40
DAMAGE_PCT = 0.03
MARGIN_PCT = 0.25


def pincode_risk(pincode: str | None) -> float:
    if not pincode or not re.fullmatch(r"\d{6}", pincode):
        return 0.30
    return HIGH_RISK_PREFIXES.get(pincode[:2], 0.12) + (int(pincode[-2:]) % 7) / 100


def address_quality(address: str | None) -> float:
    if not address:
        return 0.0
    q = 0.25 * (len(address) > 25) + 0.25 * bool(re.search(r"\d", address)) + \
        0.25 * bool(re.search(r"(near|opp|landmark|behind|road|street|nagar|colony)", address, re.I)) + \
        0.25 * (address.count(",") >= 2)
    return q


def rto_probability(order: dict, history: dict | None = None) -> dict:
    history = history or {}
    cod = order.get("payment_mode", "prepaid") == "COD"
    z = -2.6 + (1.5 if cod else -1.0)
    factors = []

    def add(label, w):
        nonlocal z
        z += w
        factors.append({"factor": label, "weight": round(w, 2)})

    pr = pincode_risk(order.get("pincode"))
    add(f"pincode risk {pr:.0%}", 6 * (pr - 0.12))
    aq = address_quality(order.get("address"))
    if aq < 0.5:
        add(f"poor address quality ({aq:.0%})", (0.5 - aq) * 2.4)
    v = order.get("amount", 0)
    if v > 5000 and cod:
        add("high-value COD order", min(1.2, v / 20000))
    if history.get("prior_rto", 0):
        add(f"{history['prior_rto']} previous RTO(s)", min(2.0, history["prior_rto"] * 1.1))
    if history.get("prior_orders", 0) >= 3 and not history.get("prior_rto"):
        add("repeat customer with clean delivery history", -0.9)
    if order.get("new_device"):
        add("new device", 0.4)
    hr = order.get("order_hour")
    if hr is not None and (hr >= 23 or hr <= 4):
        add("late-night order", 0.5)
    p = 1 / (1 + math.exp(-z))
    return {"rto_probability": round(p, 3), "cod": cod, "factors": sorted(factors, key=lambda f: -abs(f["weight"]))[:4]}


def rto_candidates(order: dict, history: dict | None, policy) -> tuple[list[Candidate], dict]:
    score = rto_probability(order, history)
    p, A = score["rto_probability"], order.get("amount", 0)
    loss = ROUND_TRIP_SHIPPING_INR + HANDLING_INR + DAMAGE_PCT * A       # ₹ lost if this order goes RTO
    margin = MARGIN_PCT * A
    incentive = min(0.03 * A, 50)
    cands = [
        Candidate("ship_as_is", "Ship as is", p_success=0, value=0, category="order"),
        Candidate("otp_verify", "OTP confirmation before dispatch", p_success=0.30,
                  value=p * loss, cost=1.5, risk_cost=0.02 * margin, category="order", channel="sms",
                  note="cuts RTO ~30% for ~2% order drop-off"),
        Candidate("call_verify", "Call to verify address and intent", p_success=0.45, value=p * loss, cost=22,
                  risk_cost=0.04 * margin, category="order", note="cuts RTO ~45% but costs agent time"),
        Candidate("prepaid_nudge", f"Nudge to prepaid with ₹{incentive:,.0f} incentive", p_success=0.35 * 0.95,
                  value=p * loss, cost=1, risk_cost=0.06 * margin, spend=incentive * 0.35, budget="prepaid_incentive",
                  category="order", channel="sms", params={"incentive_inr": incentive},
                  note="converted orders are no longer COD-risk"),
        Candidate("hold_order", "Hold order for manual review", p_success=0.5, value=p * loss, cost=15,
                  risk_cost=0.10 * margin, category="order", note="delays dispatch"),
        Candidate("block_order", "Block the order", p_success=1.0, value=p * loss, cost=0,
                  risk_cost=(1 - p) * margin, category="order", note="loses the sale for legitimate buyers"),
    ]
    return cands, {**score, "expected_rto_loss_inr": round(p * loss, 2), "loss_if_rto_inr": round(loss, 2)}
