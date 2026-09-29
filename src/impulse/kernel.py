"""The Decision Kernel: one contract for every module.

    Case -> candidate actions -> guardrails/budget/autonomy -> Decision (with rejected alternatives)

    EV = P(success) x value - cost - risk_cost
"""

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

from .policy import Policy


@dataclass
class Candidate:
    action: str
    label: str
    p_success: float = 1.0
    value: float = 0.0          # ₹ gained if it works
    cost: float = 0.0           # ₹ to execute
    risk_cost: float = 0.0      # annoyance / churn / fraud / compliance exposure in ₹
    category: str = "internal"  # payment | dispute | communication | commercial | order | internal
    channel: Optional[str] = None
    params: dict = field(default_factory=dict)
    spend: float = 0.0          # draw against a merchant budget
    budget: Optional[str] = None
    note: str = ""              # one-line rationale contributed by the module
    info_bonus: float = 0.0     # option value of learning (exploration); shrinks as evidence accumulates

    @property
    def ev(self) -> float:
        return self.p_success * self.value - self.cost - self.risk_cost + self.info_bonus


@dataclass
class Case:
    module: str
    customer_id: str
    amount: float                      # ₹ at stake
    features: dict = field(default_factory=dict)
    passport: dict = field(default_factory=dict)
    deadline: Optional[str] = None
    kind: str = ""
    must_act: bool = False             # loss-minimising decisions (disputes, refunds): pick the least-bad option
    id: str = field(default_factory=lambda: f"case_{uuid.uuid4().hex[:8]}")
    created_at: float = field(default_factory=time.time)


@dataclass
class Decision:
    case_id: str
    module: str
    mode: str                           # auto | approve | recommend | skip
    chosen: Optional[dict]
    ev: float
    reason: str
    rejected: list
    guardrails_triggered: list
    policy_version: int
    id: str = field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:8]}")
    decided_at: float = field(default_factory=time.time)
    model_versions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


DO_NOTHING = Candidate(action="do_nothing", label="Do nothing", p_success=0, value=0)

Guardrail = Callable[[Case, Candidate, "KernelContext"], Optional[str]]


class KernelContext:
    """Mutable state guardrails need: budgets spent this month and recent contacts per customer."""

    def __init__(self, now=time.time):
        self.spend: dict[str, float] = {}
        self.contacts: dict[str, list] = {}
        self.now = now

    def contacts_in(self, customer_id: str, days: int = 7) -> int:
        cutoff = self.now() - days * 86400
        return sum(1 for t in self.contacts.get(customer_id, []) if t >= cutoff)


# ── built-in guardrails ─────────────────────────────────────────────────────

def g_no_retry_hard(case, cand, ctx):
    if cand.action.startswith("retry") or cand.action == "schedule_retry":
        if case.features.get("decline_category") == "hard":
            return "hard decline: retrying can never succeed and risks issuer flags"
    return None


def g_retry_cap(case, cand, ctx, cap=4):
    if cand.action == "schedule_retry" and case.features.get("retries_so_far", 0) >= cap:
        return f"retry cap reached ({cap} attempts)"
    return None


def g_contact_cap(case, cand, ctx, cap=3):
    if cand.category == "communication" or cand.channel:
        if ctx.contacts_in(case.customer_id) >= cap:
            return f"contact frequency cap reached ({cap} messages / 7 days)"
    return None


def g_opt_out(case, cand, ctx):
    if (cand.category == "communication" or cand.channel) and case.passport.get("opted_out"):
        return "customer opted out of communication"
    return None


def g_no_reward_serial_abusers(case, cand, ctx):
    if cand.action in ("discount", "win_back_offer", "partial_refund_goodwill") and case.passport.get("serial_abuser"):
        return "serial refunder/disputer: no discounts or win-back incentives"
    return None


def g_compliance(case, cand, ctx):
    return cand.params.get("compliance_violation")


def make_kernel_guardrails(policy: Policy) -> dict[str, Guardrail]:
    def discount_ceiling(case, cand, ctx):
        if cand.action == "discount":
            ltv = case.passport.get("value_score", 0)
            ceiling = policy["discount_ceiling_pct_of_ltv"] * ltv
            if cand.spend > ceiling:
                return f"discount ₹{cand.spend:,.0f} exceeds LTV ceiling ₹{ceiling:,.0f} ({policy['discount_ceiling_pct_of_ltv']:.0%} of LTV)"
        return None

    def offer_budget(case, cand, ctx):
        if cand.budget and cand.spend:
            limit = policy["budgets_inr_per_month"].get(cand.budget, float("inf"))
            if ctx.spend.get(cand.budget, 0) + cand.spend > limit:
                return f"monthly '{cand.budget}' budget exhausted (₹{limit:,.0f})"
        return None

    return {
        "no_retry_hard_decline": g_no_retry_hard,
        "retry_cap": lambda c, k, x: g_retry_cap(c, k, x, policy["max_retries_per_payment"]),
        "contact_cap": lambda c, k, x: g_contact_cap(c, k, x, policy["contact_cap_per_7d"]),
        "opt_out": g_opt_out,
        "no_reward_serial_abusers": g_no_reward_serial_abusers,
        "recurring_compliance": g_compliance,
        "discount_ceiling": discount_ceiling,
        "offer_budget": offer_budget,
    }


class Kernel:
    def __init__(self, policy: Policy | None = None):
        self.policy = policy or Policy()
        self.ctx = KernelContext()

    def _explain(self, cand: Candidate) -> str:
        parts = [f"P={cand.p_success:.0%} × ₹{cand.value:,.0f}"]
        if cand.cost:
            parts.append(f"− cost ₹{cand.cost:,.0f}")
        if cand.risk_cost:
            parts.append(f"− risk ₹{cand.risk_cost:,.0f}")
        return f"{cand.label}: {cand.note + '; ' if cand.note else ''}EV ₹{cand.ev:,.0f} ({' '.join(parts)})"

    def decide(self, case: Case, candidates: list[Candidate], model_versions: dict | None = None) -> Decision:
        guards = make_kernel_guardrails(self.policy)
        enabled = self.policy["guardrails"]
        eligible, rejected, triggered = [], [], []
        for cand in candidates:
            violation = None
            for name, fn in guards.items():
                if enabled.get(name, True) and (violation := fn(case, cand, self.ctx)):
                    triggered.append({"guardrail": name, "action": cand.action, "message": violation})
                    break
            if violation:
                rejected.append({"action": cand.action, "label": cand.label, "ev": round(cand.ev, 2),
                                 "why": f"blocked by guardrail: {violation}"})
            else:
                eligible.append(cand)
        eligible.sort(key=lambda c: c.ev, reverse=True)
        best = eligible[0] if eligible else None

        if best is not None and best.ev <= 0 and case.must_act:
            pass  # least-cost option wins even when its EV is not positive
        elif best is None or best.ev <= 0:
            for c in eligible:
                rejected.append({"action": c.action, "label": c.label, "ev": round(c.ev, 2),
                                 "why": "expected value is not positive"})
            return Decision(case.id, case.module, "skip", None, 0.0,
                            "No action has positive expected value after cost and risk; leaving as is.",
                            rejected, triggered, self.policy["version"], model_versions=model_versions or {})

        for c in eligible[1:]:
            rejected.append({"action": c.action, "label": c.label, "ev": round(c.ev, 2),
                             "why": f"EV ₹{c.ev:,.0f} is ₹{best.ev - c.ev:,.0f} below the chosen action"})
        mode = self.policy.autonomy_for(case.module, best.action)
        note = ""
        if mode == "auto" and case.amount > self.policy["approval_threshold_inr"]:
            mode, note = "approve", f" Routed for approval: ₹{case.amount:,.0f} exceeds the ₹{self.policy['approval_threshold_inr']:,.0f} auto limit."
        if best.ev <= 0:
            note += " (least-cost option: every alternative loses more)"
        reason = self._explain(best) + note
        chosen = {**asdict(best), "ev": round(best.ev, 2)}
        return Decision(case.id, case.module, mode, chosen, round(best.ev, 2), reason, rejected, triggered,
                        self.policy["version"], model_versions=model_versions or {})

    def commit(self, case: Case, decision: Decision):
        """Charge budgets and contact caps once an action is actually going ahead."""
        ch = decision.chosen
        if not ch:
            return
        if ch.get("budget") and ch.get("spend"):
            self.ctx.spend[ch["budget"]] = self.ctx.spend.get(ch["budget"], 0) + ch["spend"]
        if ch.get("category") == "communication" or ch.get("channel"):
            self.ctx.contacts.setdefault(case.customer_id, []).append(self.ctx.now())
