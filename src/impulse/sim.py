"""Replay Lab: a simulated merchant world with HIDDEN ground truth.

Because we know the true retry-success surface, we can run three policies against the same failed
payments (common random numbers) and measure lift with real confidence intervals, including the
holdout-arm attribution the ledger would use in production.

IMPORTANT: this is a simulated world. Its ground truth encodes our assumptions. The mechanism
(learn online, measure against a holdout) is real; the absolute numbers will differ on real data.
"""

import json
import math
import os
import random
import statistics
from datetime import datetime, timedelta, timezone

from .kernel import Case, Kernel
from .ledger import Ledger
from .payments import ARMS, RetryBandit, arm_time, compliant_arms, payment_candidates
from .policy import Policy
from .schema import PaymentAttempt
from .declines import CATEGORY

DISCLOSURE = ("Simulated world: ground truth encodes our own assumptions about retry behaviour. The mechanism "
              "(a bandit that learns from outcomes, measured against a holdout) is real; absolute numbers will "
              "differ on your data.")

MIX = [("insufficient_funds", .35), ("do_not_honor", .15), ("bank_downtime", .12), ("limit_exceeded", .06),
       ("other", .04), ("auth_required", .08), ("expired_card", .12), ("lost_stolen", .02),
       ("invalid_card", .04), ("suspected_fraud", .02)]
T_CRIT = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23}
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ── hidden ground truth ─────────────────────────────────────────────────────

def true_retry_p(code: str, fail_dt: datetime, retry_dt: datetime) -> float:
    """True probability a retry at `retry_dt` succeeds. Unknown to every policy."""
    hrs = (retry_dt - fail_dt).total_seconds() / 3600
    dom = retry_dt.day
    if code == "insufficient_funds":
        p = 0.64 if dom <= 5 else (0.30 if dom >= 28 else 0.13)
        return p * (0.3 if hrs < 24 else 1.0)
    if code == "bank_downtime":
        return 0.80 if hrs <= 6 else (0.62 if hrs <= 30 else 0.42)
    if code == "do_not_honor":
        return 0.14 if hrs < 6 else (0.38 if hrs < 30 else (0.30 if hrs < 100 else 0.22)) * (1.15 if dom <= 5 else 1.0)
    if code == "limit_exceeded":
        return 0.05 if hrs < 20 else (0.64 if hrs < 30 else 0.36)
    if code == "auth_required":
        return 0.02
    if code in ("expired_card", "lost_stolen", "invalid_card", "suspected_fraud"):
        return 0.0
    return 0.22


def true_link_p(category: str, engagement: float) -> float:
    return min(0.95, {"hard": 0.42, "auth": 0.55, "soft": 0.30, "bank": 0.28}[category] * engagement)


# ── world ───────────────────────────────────────────────────────────────────

def generate_world(seed: int, n: int, weeks: int = 12) -> list[dict]:
    rng = random.Random(seed)
    codes, weights = zip(*MIX)
    world = []
    for i in range(n):
        code = rng.choices(codes, weights)[0]
        fail_dt = EPOCH + timedelta(days=rng.random() * weeks * 7)
        fail_dt = fail_dt.replace(hour=rng.choice([8, 10, 12, 14, 16, 19, 22]), minute=0, second=0, microsecond=0)
        world.append({
            "id": f"sim_{seed}_{i}", "code": code, "category": CATEGORY[code], "fail_dt": fail_dt,
            "amount": round(math.exp(rng.gauss(7.1, 0.7)), 2),          # median ≈ ₹1,200
            "recurring": rng.random() < 0.7, "engagement": max(0.3, min(1.6, rng.gauss(1.0, 0.3))),
            "ltv_months": rng.choice([6, 12, 18, 24]),
            "u_retry": [rng.random() for _ in range(6)], "u_link": rng.random(), "u_upi": rng.random(),
            "u_pause": rng.random(), "u_churn": rng.random(), "u_hold": rng.random(),
            "week": int((fail_dt - EPOCH).days // 7),
        })
    world.sort(key=lambda c: c["fail_dt"])
    return world


def _outcome(case, recovered, n_retries, pause_accepted=False) -> dict:
    """Involuntary churn: unrecovered payments churn 60% of the time; retry fatigue adds 5% per failed retry."""
    churn_p = 0.0
    if not case["recurring"]:
        return {"recovered": case["amount"] if recovered else 0.0, "ok": bool(recovered), "retries": n_retries,
                "churned": False, "churn_loss": 0.0}
    if not recovered:
        churn_p = 0.20 if pause_accepted else 0.60
    churn_p += 0.05 * max(0, n_retries - (1 if recovered else 0))
    churned = case["u_churn"] < min(churn_p, 0.95)
    return {"recovered": case["amount"] if recovered else 0.0, "ok": bool(recovered), "retries": n_retries,
            "churned": churned, "churn_loss": case["amount"] * case["ltv_months"] if churned else 0.0}


# ── policies ────────────────────────────────────────────────────────────────

def policy_baseline(case) -> dict:
    """The merchant's original logic: retry at +1d, +3d, +5d regardless of decline type, never send a link."""
    code, t = case["code"], case["fail_dt"]
    n = 0
    for k, days in enumerate((1, 3, 5)):
        at = t + timedelta(days=days)
        n += 1
        if case["u_retry"][k] < true_retry_p(code, t, at):
            return _outcome(case, True, n)
    return _outcome(case, False, n)


def policy_rules(case) -> dict:
    """A static best-practice playbook: soft -> +3d,+7d then link; hard/auth -> link at once; downtime -> +2h."""
    code, cat, t = case["code"], case["category"], case["fail_dt"]
    def links(n_retries):
        ok = case["u_link"] < true_link_p(cat, case["engagement"]) or case["u_upi"] < 0.8 * true_link_p(cat, case["engagement"])
        return _outcome(case, ok, n_retries)   # same channels as Impulse: link, then UPI fallback

    if cat in ("hard", "auth"):
        return links(0)
    n = 0
    schedule = (2 / 24, 1) if cat == "bank" else (3, 7)
    for k, days in enumerate(schedule):
        n += 1
        if case["u_retry"][k] < true_retry_p(code, t, t + timedelta(days=days)):
            return _outcome(case, True, n)
    return links(n)


class ImpulsePolicy:
    """Runs the REAL kernel + bandit (same code as production) against the simulated world."""

    def __init__(self, seed: int = 0, learn: bool = True):
        self.bandit = RetryBandit(seed=seed)
        self.policy = Policy()
        self.kernel = Kernel(self.policy)
        self.learn = learn

    def run(self, case) -> dict:
        code, cat, t0 = case["code"], case["category"], case["fail_dt"]
        now, retries, streak, recovered, pause = t0, 0, 1, False, False
        used_links = set()
        for _ in range(6):
            att = PaymentAttempt(id=case["id"], customer_id=case["id"], amount=case["amount"], status="failed",
                                 decline_code=code, decline_category=cat, gateway="razorpay",
                                 attempted_at=t0.isoformat(), is_recurring=case["recurring"])
            passport = {"value_score": case["amount"] * case["ltv_months"], "monthly_revenue": case["amount"],
                        "churn_risk": min(0.9, 0.12 + 0.28 * (streak - 1)),
                        "payment_health": {"failure_streak": streak}}
            cands, meta = payment_candidates(att, passport, self.bandit, self.policy, now, retries_so_far=retries,
                                             explore=self.learn)
            cands = [c for c in cands if not (c.action in used_links)]
            kcase = Case("payments", case["id"], case["amount"],
                         {"decline_category": cat, "retries_so_far": retries}, passport)
            dec = self.kernel.decide(kcase, cands)
            ch = dec.chosen
            if ch is None:
                break
            act = ch["action"]
            if act == "schedule_retry":
                at = datetime.fromisoformat(ch["params"]["retry_at"])
                ok = case["u_retry"][retries] < true_retry_p(code, t0, at)
                if self.learn:
                    self.bandit.update(ch["params"]["context"], ch["params"]["arm"], ok)
                retries += 1
                if ok:
                    recovered = True
                    break
                streak += 1
                now = at
            elif act in ("payment_update_link", "upi_fallback"):
                used_links.add(act)
                p = true_link_p(cat, case["engagement"]) * (0.8 if act == "upi_fallback" else 1.0)
                u = case["u_link"] if act == "payment_update_link" else case["u_upi"]
                if u < p:
                    recovered = True
                    break
                now += timedelta(days=2)
                streak += 1
            elif act == "offer_pause":
                used_links.add(act)
                if case["u_pause"] < 0.32:
                    pause = True
                    break
                streak += 1
            else:
                break
        return _outcome(case, recovered, retries, pause_accepted=pause)


# ── replay ──────────────────────────────────────────────────────────────────

def _summarise(results: list[dict], world: list[dict]) -> dict:
    amount = sum(c["amount"] for c in world)
    rec = sum(r["recovered"] for r in results)
    weekly = {}
    cum_rec = cum_amt = 0.0
    for w in range(max(c["week"] for c in world) + 1):
        for c, r in zip(world, results):
            if c["week"] == w:
                cum_rec += r["recovered"]
                cum_amt += c["amount"]
        weekly[w] = cum_rec / cum_amt if cum_amt else 0.0
    churn_loss = sum(r["churn_loss"] for r in results)
    return {"recovered_inr": round(rec, 2), "recovery_rate": round(rec / amount, 4),
            "retries_per_recovery": round(sum(r["retries"] for r in results) / max(sum(r["ok"] for r in results), 1), 2),
            "involuntary_churn_rate": round(sum(r["churned"] for r in results) / len(results), 4),
            "churn_loss_inr": round(churn_loss, 2), "weekly_cumulative_rate": [round(weekly[w], 4) for w in sorted(weekly)]}


def _ci(values: list[float]) -> tuple[float, float, float]:
    m = statistics.mean(values)
    if len(values) < 2:
        return m, m, m
    half = T_CRIT.get(len(values) - 1, 2.0) * statistics.stdev(values) / math.sqrt(len(values))
    return m, m - half, m + half


def run_replay(n: int = 1200, seeds: int = 5, holdout_pct: float = 10.0) -> dict:
    """Run baseline / rules / impulse on `seeds` independent worlds; returns curves, CIs and attribution check."""
    per_seed, ledger_est, true_lift, learning = [], [], [], []
    heat = None
    for s in range(seeds):
        world = generate_world(1000 + s, n)
        imp = ImpulsePolicy(seed=s)
        frozen = ImpulsePolicy(seed=s, learn=False)   # same kernel + rule priors, never learns: isolates the bandit's value
        ledger = Ledger(min_holdout=15)
        res = {"baseline": [], "rules": [], "frozen": [], "impulse": []}
        hold_rng = random.Random(77 + s)
        for c in world:
            b, r = policy_baseline(c), policy_rules(c)
            i = imp.run(c)
            res["frozen"].append(frozen.run(c))
            is_hold = hold_rng.random() < holdout_pct / 100
            res["baseline"].append(b)
            res["rules"].append(r)
            # a holdout case is actually served by the merchant's original logic, not by Impulse
            res["impulse"].append(b if is_hold else i)
            ledger.record(case_id=c["id"], module="payments", action="recovery_journey",
                          amount_at_stake=c["amount"], recovered=(b if is_hold else i)["recovered"],
                          cost=0.0, arm="holdout" if is_hold else "treatment", at=c["fail_dt"].timestamp())
        summaries = {k: _summarise(v, world) for k, v in res.items()}
        per_seed.append(summaries)
        est = ledger.summary()["by_module"]["payments"]
        treated = [(c, i) for c, i, rb in zip(world, res["impulse"], res["baseline"]) if i is not rb]
        true_incr = sum(i["recovered"] - policy_baseline(c)["recovered"] for c, i in treated)
        ledger_est.append(est["incremental"])
        true_lift.append(true_incr)
        learning.append(imp.bandit.observations())
        if s == 0:
            heat = {code: imp.bandit.heatmap(code) for code in ("insufficient_funds", "bank_downtime", "limit_exceeded")}
    out = {"config": {"cases_per_world": n, "worlds": seeds, "holdout_pct": holdout_pct, "weeks": 12},
           "policies": {}, "disclosure": DISCLOSURE}
    for pol in ("baseline", "rules", "frozen", "impulse"):
        rate = _ci([s[pol]["recovery_rate"] for s in per_seed])
        churn = _ci([s[pol]["involuntary_churn_rate"] for s in per_seed])
        weekly = [statistics.mean(s[pol]["weekly_cumulative_rate"][w] for s in per_seed)
                  for w in range(len(per_seed[0][pol]["weekly_cumulative_rate"]))]
        out["policies"][pol] = {
            "recovery_rate": {"mean": round(rate[0], 4), "lo": round(rate[1], 4), "hi": round(rate[2], 4)},
            "involuntary_churn_rate": {"mean": round(churn[0], 4), "lo": round(churn[1], 4), "hi": round(churn[2], 4)},
            "recovered_inr": round(statistics.mean(s[pol]["recovered_inr"] for s in per_seed), 2),
            "churn_loss_inr": round(statistics.mean(s[pol]["churn_loss_inr"] for s in per_seed), 2),
            "net_value_inr": round(statistics.mean(s[pol]["recovered_inr"] - s[pol]["churn_loss_inr"] for s in per_seed), 2),
            "retries_per_recovery": round(statistics.mean(s[pol]["retries_per_recovery"] for s in per_seed), 2),
            "weekly_cumulative_rate": [round(w, 4) for w in weekly]}
    b, i = out["policies"]["baseline"], out["policies"]["impulse"]
    lifts = [s["impulse"]["recovery_rate"] - s["baseline"]["recovery_rate"] for s in per_seed]
    lm = _ci(lifts)
    out["lift"] = {"recovery_rate_pts": {"mean": round(lm[0] * 100, 2), "lo": round(lm[1] * 100, 2), "hi": round(lm[2] * 100, 2)},
                   "relative_pct": round((i["recovery_rate"]["mean"] / b["recovery_rate"]["mean"] - 1) * 100, 1),
                   "extra_recovered_inr": round(i["recovered_inr"] - b["recovered_inr"], 2),
                   "churn_loss_avoided_inr": round(b["churn_loss_inr"] - i["churn_loss_inr"], 2),
                   "vs_rules_net_value_inr": round(i["net_value_inr"] - out["policies"]["rules"]["net_value_inr"], 2),
                   "learning_gain_pts": round((i["recovery_rate"]["mean"] - out["policies"]["frozen"]["recovery_rate"]["mean"]) * 100, 2),
                   "learning_gain_net_inr": round(i["net_value_inr"] - out["policies"]["frozen"]["net_value_inr"], 2)}
    out["attribution_check"] = {
        "ledger_estimated_incremental_inr": round(statistics.mean(ledger_est), 2),
        "true_incremental_inr": round(statistics.mean(true_lift), 2),
        "note": "Ledger estimate uses the 10% holdout arm as the baseline; 'true' uses the simulated counterfactual "
                "for the same treated cases. Agreement shows the attribution method is honest, not just favourable."}
    out["bandit"] = {"observations_per_world": round(statistics.mean(learning)), "heatmap": heat,
                     "arms": {k: v["label"] for k, v in ARMS.items()}}
    return out


CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "results", "replay_lab.json")


def cached_replay() -> dict:
    """Precomputed default run (serverless-friendly). Falls back to a small live run."""
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as fh:
            return json.load(fh)
    return run_replay(n=400, seeds=3)


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
    res = run_replay(n=n, seeds=5)
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps({k: res[k] for k in ("lift", "attribution_check")}, indent=1))
    for p, v in res["policies"].items():
        print(p, v["recovery_rate"], v["involuntary_churn_rate"]["mean"], v["retries_per_recovery"])
