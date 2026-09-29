"""Payment Recovery (failed money): retry-timing bandit, recovery journeys, pre-dunning,
checkout routing advice and India recurring-debit compliance.

Compliance constants are modelling defaults. VERIFY the current RBI e-mandate thresholds
and notification timelines before relying on them in production.
"""

import math
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .kernel import Candidate

PRE_DEBIT_NOTICE_HOURS = 24      # verify against current RBI e-mandate rules
AFA_LIMIT_INR = 15000            # above this, recurring debits need additional factor authentication (verify)

ARMS = {
    "in_2h": {"label": "in 2 hours", "delay_h": 2},
    "next_morning": {"label": "next morning 10:00", "delay_h": None},
    "plus_3d": {"label": "in 3 days", "delay_h": 72},
    "salary_window": {"label": "next salary window (1st–5th)", "delay_h": None},
    "plus_7d": {"label": "in 7 days", "delay_h": 168},
}

# Rule priors (mean success probability per decline code x arm). Deliberately reasonable-but-imperfect:
# the bandit's job is to correct them from live outcomes.
PRIOR_MEANS = {
    "insufficient_funds": {"in_2h": 0.08, "next_morning": 0.20, "plus_3d": 0.30, "salary_window": 0.50, "plus_7d": 0.32},
    "bank_downtime": {"in_2h": 0.55, "next_morning": 0.50, "plus_3d": 0.35, "salary_window": 0.30, "plus_7d": 0.25},
    "do_not_honor": {"in_2h": 0.15, "next_morning": 0.30, "plus_3d": 0.30, "salary_window": 0.30, "plus_7d": 0.25},
    "limit_exceeded": {"in_2h": 0.10, "next_morning": 0.38, "plus_3d": 0.30, "salary_window": 0.25, "plus_7d": 0.22},
    "other": {"in_2h": 0.20, "next_morning": 0.25, "plus_3d": 0.25, "salary_window": 0.25, "plus_7d": 0.20},
    "auth_required": {a: 0.03 for a in ARMS},
}
PRIOR_STRENGTH = 4.0


def dom_bucket(dt: datetime) -> str:
    return "start" if dt.day <= 5 else ("mid" if dt.day <= 20 else "end")


def context_key(decline_code: str, when: datetime) -> str:
    return f"{decline_code}|{dom_bucket(when)}"


def arm_time(arm: str, now: datetime) -> datetime:
    """Concrete retry time for an arm."""
    if arm == "next_morning":
        return (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    if arm == "salary_window":
        t = now + timedelta(days=1)
        while t.day > 5:
            t += timedelta(days=1)
        return t.replace(hour=10, minute=0, second=0, microsecond=0)
    return now + timedelta(hours=ARMS[arm]["delay_h"])


def compliant_arms(is_recurring: bool, now: datetime) -> list[str]:
    """Recurring debits need a pre-debit notice 24h ahead, so retries closer than that are not schedulable."""
    if not is_recurring:
        return list(ARMS)
    return [a for a in ARMS if (arm_time(a, now) - now).total_seconds() >= (PRE_DEBIT_NOTICE_HOURS + 1) * 3600]


class RetryBandit:
    """Beta-Bernoulli bandit (UCB exploration) per (decline_code, day-of-month bucket) context.

    Starts from rule priors and learns online from outcomes. State is JSON-serialisable."""

    def __init__(self, seed: int | None = None, prior_strength: float = PRIOR_STRENGTH, ucb_c: float = 0.6):
        self.rng = random.Random(seed)
        self.ucb_c = ucb_c
        self.prior_strength = prior_strength
        self.counts: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # [succ, fail]

    def _prior(self, context: str, arm: str) -> tuple[float, float]:
        code = context.split("|")[0]
        mean = PRIOR_MEANS.get(code, PRIOR_MEANS["other"])[arm]
        return mean * self.prior_strength, (1 - mean) * self.prior_strength

    POOL_WEIGHT = 0.5

    def posterior(self, context: str, arm: str) -> tuple[float, float]:
        """Rule prior + own evidence + partially-pooled evidence from the same decline code in other
        day-of-month buckets (sparse contexts borrow strength instead of over-reacting to a few outcomes)."""
        a0, b0 = self._prior(context, arm)
        s, f = self.counts[context][arm]
        code = context.split("|")[0]
        for other in ("start", "mid", "end"):
            key = f"{code}|{other}"
            if key != context and key in self.counts and arm in self.counts[key]:
                so, fo = self.counts[key][arm]
                s, f = s + self.POOL_WEIGHT * so, f + self.POOL_WEIGHT * fo
        return a0 + s, b0 + f

    def mean(self, context: str, arm: str) -> float:
        a, b = self.posterior(context, arm)
        return a / (a + b)

    def select(self, context: str, allowed: list[str] | None = None, explore: bool = True) -> str:
        """Pick a retry window. With explore=True use an upper-confidence bound (posterior mean plus a bonus
        that shrinks as evidence accumulates), so under-tried windows get tested; the Kernel still prices the
        chosen arm at its honest posterior MEAN."""
        allowed = allowed or list(ARMS)
        if not explore:
            return max(allowed, key=lambda a: self.mean(context, a))

        def ucb(arm):
            a, b = self.posterior(context, arm)
            m, sd = a / (a + b), math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))
            return m + self.ucb_c * sd
        return max(allowed, key=ucb)

    def sd(self, context: str, arm: str) -> float:
        a, b = self.posterior(context, arm)
        return math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))

    def update(self, context: str, arm: str, success: bool):
        self.counts[context][arm][0 if success else 1] += 1

    def observations(self) -> int:
        return sum(s + f for arms in self.counts.values() for s, f in arms.values())

    def heatmap(self, code: str) -> dict:
        """Posterior mean success per arm x day-of-month bucket, for the console."""
        return {b: {a: round(self.mean(f"{code}|{b}", a), 3) for a in ARMS} for b in ("start", "mid", "end")}

    def to_state(self) -> dict:
        return {c: {a: list(v) for a, v in arms.items()} for c, arms in self.counts.items()}

    @classmethod
    def from_state(cls, state: dict, seed=None):
        b = cls(seed=seed)
        for c, arms in state.items():
            for a, v in arms.items():
                b.counts[c][a] = list(v)
        return b


# ── candidates for the Kernel ───────────────────────────────────────────────

LINK_P = {"hard": 0.42, "auth": 0.60, "soft": 0.30, "bank": 0.25}


def payment_candidates(attempt, passport: dict, bandit: RetryBandit, policy, now: datetime,
                       retries_so_far: int = 0, explore: bool = True) -> tuple[list[Candidate], dict]:
    """Options for one failed payment. Returns (candidates, meta) where meta explains the bandit's choice."""
    cat, code = attempt.decline_category or "soft", attempt.decline_code or "other"
    amount = attempt.amount
    ltv = passport.get("value_score", 0) or 0
    streak = passport.get("payment_health", {}).get("failure_streak", 0)
    churn = passport.get("churn_risk", 0)
    when = datetime.fromisoformat(attempt.attempted_at.replace("Z", "+00:00")) if isinstance(attempt.attempted_at, str) else now
    cands, meta = [], {"context": None, "arm": None}

    # Recovering a recurring payment also avoids involuntary churn (cross-module: Payment <-> Retention).
    value = amount + (0.5 * ltv if attempt.is_recurring else 0.0)
    # Every FAILED retry annoys the customer; the cost grows with the failure streak (cross-module rule).
    fatigue = 0.03 * streak * (0.7 + churn)

    if cat != "hard":
        ctx = context_key(code, when)
        allowed = compliant_arms(attempt.is_recurring, now)
        arm = bandit.select(ctx, allowed, explore=explore) if allowed else None
        meta = {"context": ctx, "arm": arm, "allowed_arms": allowed,
                "posterior_means": {a: round(bandit.mean(ctx, a), 3) for a in ARMS}}
        if arm:
            retry_at = arm_time(arm, now)
            params = {"arm": arm, "arm_label": ARMS[arm]["label"], "retry_at": retry_at.isoformat(timespec="minutes"),
                      "context": ctx}
            if attempt.is_recurring:
                params["pre_debit_notice_at"] = (retry_at - timedelta(hours=PRE_DEBIT_NOTICE_HOURS)).isoformat(timespec="minutes")
            if attempt.is_recurring and amount > AFA_LIMIT_INR:
                params["compliance_violation"] = (f"recurring debit ₹{amount:,.0f} > ₹{AFA_LIMIT_INR:,.0f}: needs customer "
                                                  "authentication; automatic retry is not permitted")
            p_retry = bandit.mean(ctx, arm)
            cands.append(Candidate(
                "schedule_retry", f"Retry {ARMS[arm]['label']}", p_success=p_retry, value=value,
                cost=policy["retry_cost_inr"], risk_cost=(1 - p_retry) * fatigue * ltv, category="payment", params=params,
                info_bonus=bandit.ucb_c * bandit.sd(ctx, arm) * value if explore else 0.0,
                note=f"{code.replace('_', ' ')} is a {cat} decline; best window from the retry bandit"
                     + (f" (pre-debit notice sent 24h earlier)" if attempt.is_recurring else "")))
        elif attempt.is_recurring:
            cands.append(Candidate("schedule_retry", "Retry", p_success=0, value=0, category="payment",
                                   params={"compliance_violation": "no compliant retry window"}))
    else:
        # a hard decline can never succeed on retry: expose the option so the guardrail is visible
        cands.append(Candidate("schedule_retry", "Retry same method", p_success=0.02, value=value,
                               cost=policy["retry_cost_inr"], category="payment", note="hard decline"))

    link_p = LINK_P.get(cat, 0.3) * (0.85 if streak >= 2 else 1.0)
    cands.append(Candidate("payment_update_link", "Send payment-update link", p_success=link_p, value=value,
                           cost=policy["message_cost_inr"]["whatsapp"], category="communication", channel="whatsapp",
                           params={"channel_reason": "phone on file; UPI-friendly hosted page"},
                           note="customer supplies a working method" if cat == "hard" else "gives the customer a self-serve fix"))
    if attempt.method_type != "upi" and amount <= 100000:
        cands.append(Candidate("upi_fallback", "Offer UPI as alternate method", p_success=0.30 if cat == "hard" else 0.22,
                               value=value, cost=policy["message_cost_inr"]["sms"], category="communication", channel="sms",
                               note="UPI bypasses card issue"))
    if streak >= 2 and passport.get("monthly_revenue", 0) > 0:
        m = passport["monthly_revenue"]
        cands.append(Candidate("offer_pause", "Offer a pause instead of another retry", p_success=0.32,
                               value=m * 4 + amount * 0.2, cost=1, category="commercial", channel="in_app",
                               note=f"{streak} consecutive failures raised churn risk to {churn:.0%}: switch from retry to save offer"))
    cands.append(Candidate("do_nothing", "Do nothing", p_success=0, value=0))
    return cands, meta


# ── journeys, pre-dunning, routing ──────────────────────────────────────────

def build_journey(attempt, decision_chosen: dict | None, passport: dict, now: datetime) -> list[dict]:
    """Sequenced recovery flow, channel and timing chosen per customer."""
    cat = attempt.decline_category or "soft"
    has_phone = bool(passport.get("profile", {}).get("phone")) and not passport.get("opted_out")
    ch = "whatsapp" if has_phone else "email"
    t = lambda **kw: (now + timedelta(**kw)).isoformat(timespec="minutes")
    steps = []
    if cat == "hard":
        steps = [("payment_update_link", ch, t(minutes=5)), ("upi_fallback", "sms", t(days=1)), ("final_notice", "email", t(days=5))]
    elif cat == "auth":
        steps = [("authentication_link", ch, t(minutes=5)), ("reminder", "sms", t(days=1)), ("final_notice", "email", t(days=4))]
    else:
        retry = (decision_chosen or {}).get("params", {})
        if attempt.is_recurring and retry.get("pre_debit_notice_at"):
            steps.append(("pre_debit_notice", "sms", retry["pre_debit_notice_at"]))
        if retry.get("retry_at"):
            steps.append(("retry", "gateway", retry["retry_at"]))
        steps += [("failure_notice", ch, t(days=1, hours=1)), ("payment_update_link", ch, t(days=3)), ("final_notice", "email", t(days=7))]
    return [{"step": i + 1, "action": a, "channel": c, "at": at} for i, (a, c, at) in enumerate(steps)]


def predunning_targets(methods: list, subscriptions: list, now: datetime, window_days: int = 30) -> list[dict]:
    """Cards expiring before the next billing date get a refresh nudge."""
    subs = {s.customer_id: s for s in subscriptions if s.status in ("active", "past_due")}
    out = []
    for m in methods:
        if m.type != "card" or not m.expiry or m.customer_id not in subs:
            continue
        y, mo = map(int, m.expiry.split("-"))
        exp = datetime(y + (mo // 12), mo % 12 + 1, 1, tzinfo=timezone.utc)  # first day after expiry month
        days_left = (exp - now).days
        nxt = subs[m.customer_id].next_billing_at
        expires_before_bill = bool(nxt) and exp <= datetime.fromisoformat(str(nxt).replace("Z", "+00:00")) + timedelta(days=1)
        if days_left <= window_days and (days_left >= -30):
            out.append({"customer_id": m.customer_id, "expiry": m.expiry, "days_left": days_left,
                        "expires_before_next_bill": expires_before_bill, "amount": subs[m.customer_id].amount,
                        "action": "send_card_refresh_nudge"})
    return sorted(out, key=lambda x: x["days_left"])


def routing_advice(attempts: list, min_n: int = 20) -> dict:
    """Which gateway/method performs best at fresh checkout per bank.

    NOTE: card tokens are generally not portable across gateways, so this advises where a *new*
    checkout should route. It does not promise cross-gateway retry of a failed payment."""
    stats = defaultdict(lambda: [0, 0])
    for a in attempts:
        if a.status in ("succeeded", "failed"):
            stats[(a.bank or "unknown", a.method_type, a.gateway)][0 if a.status == "succeeded" else 1] += 1
    by_ctx = defaultdict(list)
    for (bank, method, gw), (s, f) in stats.items():
        if s + f >= min_n:
            by_ctx[(bank, method)].append({"gateway": gw, "success_rate": round(s / (s + f), 3), "n": s + f})
    advice = []
    for (bank, method), opts in by_ctx.items():
        if len(opts) < 2:
            continue
        opts.sort(key=lambda o: -o["success_rate"])
        lift = opts[0]["success_rate"] - opts[-1]["success_rate"]
        if lift >= 0.02:
            advice.append({"bank": bank, "method": method, "route_to": opts[0]["gateway"], "options": opts,
                           "lift_pts": round(lift * 100, 1)})
    return {"advice": sorted(advice, key=lambda a: -a["lift_pts"]),
            "caveat": "Advises fresh-checkout routing only; card tokens are generally not portable across gateways."}
