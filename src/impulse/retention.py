"""Retention Rescue (stopped money): churn score v1, involuntary/voluntary split, save ladder,
LTV-gated offers, persuadability, win-back. v2 model + uplift live in `models_v2.py`."""

from .kernel import Candidate

WEIGHTS = {
    "payment_friction": 0.30, "days_since_success": 0.15, "usage_decay": 0.22,
    "tickets": 0.13, "downgrades": 0.12, "seat_reductions": 0.08,
}


def score_churn(signals: dict) -> dict:
    """Weighted v1 score in [0,1] with reasons and involuntary/voluntary split."""
    friction = min(1.0, signals["failure_streak"] / 3 + 0.1 * min(signals["failures_30d"], 3))
    since = signals["days_since_last_success"]
    since_c = 0.0 if since is None else min(1.0, max(0.0, (since - 35) / 55))
    comps = {
        "payment_friction": friction,
        "days_since_success": since_c,
        "usage_decay": signals["usage_decay"],
        "tickets": min(1.0, signals["unresolved_tickets"] / 2),
        "downgrades": min(1.0, signals["downgrades"]),
        "seat_reductions": min(1.0, signals["seat_reductions"]),
    }
    score = sum(WEIGHTS[k] * v for k, v in comps.items())
    invol = WEIGHTS["payment_friction"] * comps["payment_friction"] + WEIGHTS["days_since_success"] * comps["days_since_success"]
    vol = score - invol
    if score < 0.05:
        ctype = "none"
    elif invol >= 1.5 * vol:
        ctype = "involuntary"
    elif vol >= 1.5 * invol:
        ctype = "voluntary"
    else:
        ctype = "mixed"
    labels = {"payment_friction": "payment failures", "days_since_success": "no recent successful charge",
              "usage_decay": "usage decaying", "tickets": "unresolved support tickets",
              "downgrades": "downgrade", "seat_reductions": "seat reduction"}
    reasons = [labels[k] for k, v in sorted(comps.items(), key=lambda kv: -WEIGHTS[kv[0]] * kv[1]) if v > 0.15][:3]
    return {"score": round(min(score, 1.0), 3), "type": ctype, "reasons": reasons,
            "components": {k: round(v, 2) for k, v in comps.items()}}


def persuadability(passport: dict) -> dict:
    """Heuristic: don't spend offers on people who'd stay anyway or who habitually take offers."""
    risk = passport["churn_risk"]
    if passport["serial_abuser"]:
        return {"score": 0.0, "verdict": "excluded", "why": "serial refunder/disputer"}
    if passport["offers_taken"] >= 2:
        return {"score": 0.15, "verdict": "offer_taker", "why": f"has taken {passport['offers_taken']} offers already"}
    if risk < 0.25:
        return {"score": 0.1, "verdict": "would_stay", "why": "low churn risk: would likely stay without an offer"}
    if risk > 0.92:
        return {"score": 0.25, "verdict": "likely_lost", "why": "very high risk: a discount rarely changes the outcome"}
    return {"score": round(0.35 + 0.5 * (1 - abs(risk - 0.6) / 0.6), 2), "verdict": "persuadable", "why": "moderate-to-high risk with recoverable signals"}


def retention_candidates(passport: dict, policy) -> list[Candidate]:
    """The save-action ladder, cheapest effective first. Returns Kernel candidates."""
    risk, ctype = passport["churn_risk"], passport["churn_type"]
    monthly, ltv = passport["monthly_revenue"], passport["value_score"]
    pers = persuadability(passport)
    at_risk = risk * ltv
    cands = []
    pay_fix_p = 0.55 if ctype in ("involuntary", "mixed") else 0.05
    cands.append(Candidate("payment_update_link", "Send payment-update link", p_success=pay_fix_p, value=at_risk,
                           cost=0.5, category="communication", channel="email",
                           note="fixes the card problem behind involuntary churn" if pay_fix_p > 0.1 else "payment is not the problem"))
    cands.append(Candidate("offer_pause", "Offer a pause instead of cancelling", p_success=0.35 * (0.5 + pers["score"]),
                           value=monthly * 4, cost=1, risk_cost=0.02 * monthly, category="commercial", channel="in_app",
                           note="keeps the relationship at near-zero cost"))
    cands.append(Candidate("offer_downgrade", "Offer a cheaper plan", p_success=0.30 * (0.5 + pers["score"]),
                           value=monthly * 0.6 * 6, cost=1, category="commercial", channel="email",
                           note="retains partial revenue"))
    if at_risk > 4000:
        cands.append(Candidate("personal_outreach", "Personal outreach call", p_success=0.42 * (0.5 + pers["score"]),
                               value=at_risk, cost=180, category="internal",
                               note="high-value account justifies human time"))
    # a discount cannot fix a card problem: its odds depend on how much of the churn is voluntary
    vol_factor = {"voluntary": 1.0, "mixed": 0.7, "involuntary": 0.25}.get(ctype, 0.5)
    pct = 0.2
    disc = monthly * 3 * pct
    cands.append(Candidate("discount", f"Offer {pct:.0%} off for 3 months", p_success=min(0.8, 0.55 * pers["score"] * 1.6 * vol_factor),
                           value=at_risk, cost=disc, risk_cost=0.0, category="commercial", channel="email",
                           spend=disc, budget="offers", params={"discount_pct": pct * 100, "months": 3},
                           note="last rung of the ladder"))
    cands.append(Candidate("recommend_only_flag", "Flag in CRM for account manager", p_success=0.12, value=at_risk,
                           cost=0.2, category="internal", note="low-cost passive option"))
    return cands


def winback_candidates(passport: dict, policy) -> list[Candidate]:
    monthly = passport["monthly_revenue"] or 500.0
    return [Candidate("win_back_offer", "Win-back offer (2 months half price)", p_success=0.08 * (passport["trust_score"] / 100),
                      value=monthly * 8, cost=monthly * 1.0, spend=monthly * 1.0, budget="offers", category="commercial",
                      channel="email", note="already-lost customer; excluded if trust is poor")]
