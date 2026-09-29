"""Decision Kernel, guardrails, and the module decision logic (payments, refunds, RTO, disputes, retention)."""

import time
from datetime import datetime, timezone

import pytest

from src.impulse.clawback import deadline_status, dispute_candidates
from src.impulse.kernel import Candidate, Case, Kernel
from src.impulse.payments import (AFA_LIMIT_INR, ARMS, RetryBandit, compliant_arms, context_key, payment_candidates, predunning_targets,
                                  routing_advice)
from src.impulse.policy import Policy
from src.impulse.refunds import abuse_score, refund_candidates
from src.impulse.retention import persuadability, retention_candidates, score_churn
from src.impulse.rto import rto_candidates, rto_probability
from src.impulse.schema import PaymentAttempt, PaymentMethod, Subscription

NOW = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)


def kernel(**overrides):
    return Kernel(Policy(overrides or None))


def case(module="payments", amount=1000, **kw):
    return Case(module, "c1", amount, kw.pop("features", {}), kw.pop("passport", {}), **kw)


class TestKernel:
    def test_picks_highest_ev_and_stores_rejected_alternatives(self):
        d = kernel().decide(case(), [Candidate("schedule_retry", "Retry", 0.5, 1000), Candidate("payment_update_link", "Link", 0.3, 1000), Candidate("do_nothing", "Nothing")])
        assert d.chosen["action"] == "schedule_retry" and d.ev == 500
        assert {r["action"] for r in d.rejected} == {"payment_update_link", "do_nothing"}
        assert "EV" in d.reason

    def test_no_positive_ev_means_skip(self):
        d = kernel().decide(case(), [Candidate("schedule_retry", "Retry", 0.01, 100, cost=5)])
        assert d.mode == "skip" and d.chosen is None

    def test_must_act_picks_least_bad_option(self):
        d = kernel().decide(case(must_act=True), [Candidate("accept_liability", "Accept", 1, 0), Candidate("submit_evidence", "Fight", 1, -50)])
        assert d.chosen["action"] == "accept_liability" and d.mode != "skip"

    def test_hard_decline_never_retried(self):
        d = kernel().decide(case(features={"decline_category": "hard"}), [Candidate("schedule_retry", "Retry", 0.9, 5000, category="payment"), Candidate("payment_update_link", "Link", 0.2, 5000, channel="email")])
        assert d.chosen["action"] == "payment_update_link"
        assert d.guardrails_triggered[0]["guardrail"] == "no_retry_hard_decline"

    def test_contact_frequency_cap(self):
        k = kernel()
        c = case()
        for _ in range(3):
            k.ctx.contacts.setdefault("c1", []).append(time.time())
        d = k.decide(c, [Candidate("payment_update_link", "Link", 0.5, 1000, channel="email"), Candidate("schedule_retry", "Retry", 0.2, 1000)])
        assert d.chosen["action"] == "schedule_retry"

    def test_serial_abuser_gets_no_discount(self):
        d = kernel().decide(case("retention", passport={"serial_abuser": True, "value_score": 90000}),
                            [Candidate("discount", "Discount", 0.8, 5000, spend=100, budget="offers", channel="email"), Candidate("offer_pause", "Pause", 0.2, 5000, channel="in_app")])
        assert d.chosen["action"] == "offer_pause"

    def test_discount_ceiling_tied_to_ltv(self):
        d = kernel().decide(case("retention", passport={"value_score": 1000}), [Candidate("discount", "Discount", 0.9, 5000, spend=500, budget="offers", channel="email"), Candidate("offer_pause", "Pause", 0.1, 5000)])
        assert d.chosen["action"] == "offer_pause" and any(g["guardrail"] == "discount_ceiling" for g in d.guardrails_triggered)

    def test_budget_exhaustion_blocks_and_commit_charges(self):
        k = kernel(budgets_inr_per_month={"offers": 100})
        cand = lambda: Candidate("discount", "Discount", 0.9, 5000, spend=80, budget="offers", channel="email")
        c = case("retention", passport={"value_score": 100000})
        d1 = k.decide(c, [cand()])
        assert d1.chosen
        k.commit(c, d1)
        d2 = k.decide(c, [cand(), Candidate("offer_pause", "Pause", 0.2, 5000)])
        assert d2.chosen["action"] == "offer_pause"

    def test_autonomy_levels_and_high_value_override(self):
        c = Candidate("schedule_retry", "Retry", 0.5, 1000)
        assert kernel().decide(case(), [c]).mode == "auto"
        assert kernel().decide(case(amount=90000), [c]).mode == "approve"
        assert kernel(autonomy={"payments": "recommend"}, action_overrides={"schedule_retry": "recommend"}).decide(case(), [c]).mode == "recommend"
        assert kernel().decide(case("clawback"), [Candidate("accept_liability", "Accept", 1, 100)]).mode == "approve"

    def test_policy_validation(self):
        p = Policy()
        with pytest.raises(ValueError):
            p.update({"autonomy": {"payments": "yolo"}})
        with pytest.raises(ValueError):
            p.update({"holdout_pct": 90})
        with pytest.raises(ValueError):
            p.update({"nonsense": 1})
        assert p.update({"fee_pct": 15})["version"] == 2


def attempt(code="insufficient_funds", cat="soft", amount=1299, recurring=True, method="card"):
    return PaymentAttempt(id="p1", customer_id="c1", amount=amount, status="failed", decline_code=code, decline_category=cat,
                          attempted_at=NOW.isoformat(), gateway="razorpay", is_recurring=recurring, method_type=method)


class TestPayments:
    def test_recurring_retries_respect_pre_debit_notice(self):
        arms = compliant_arms(True, NOW)
        assert "in_2h" not in arms and "salary_window" in arms
        afternoon = NOW.replace(hour=15)                     # next 10:00 is only 19h away: too close for a 24h notice
        assert "next_morning" not in compliant_arms(True, afternoon)
        assert set(compliant_arms(False, NOW)) == set(ARMS)

    def test_bandit_starts_at_prior_and_learns(self):
        b = RetryBandit(seed=1)
        ctx = context_key("limit_exceeded", NOW)
        prior = b.mean(ctx, "next_morning")
        for _ in range(40):
            b.update(ctx, "next_morning", True)
        assert b.mean(ctx, "next_morning") > prior + 0.2
        for _ in range(60):
            b.update(ctx, "plus_7d", False)
        assert b.mean(ctx, "plus_7d") < 0.15
        assert b.observations() == 100

    def test_bandit_state_roundtrip(self):
        b = RetryBandit()
        b.update("other|mid", "plus_3d", True)
        assert RetryBandit.from_state(b.to_state()).mean("other|mid", "plus_3d") == b.mean("other|mid", "plus_3d")

    def test_soft_decline_gets_retry_with_notice_for_recurring(self):
        cands, meta = payment_candidates(attempt(), {"value_score": 20000, "payment_health": {"failure_streak": 1}, "churn_risk": 0.1}, RetryBandit(seed=0), Policy(), NOW)
        retry = next(c for c in cands if c.action == "schedule_retry")
        assert "pre_debit_notice_at" in retry.params and meta["arm"] in ARMS

    def test_large_recurring_debit_requires_authentication(self):
        cands, _ = payment_candidates(attempt(amount=AFA_LIMIT_INR + 5000), {"value_score": 0, "payment_health": {"failure_streak": 1}}, RetryBandit(seed=0), Policy(), NOW)
        d = kernel().decide(case(amount=20000), cands)
        assert d.chosen["action"] != "schedule_retry" and any(g["guardrail"] == "recurring_compliance" for g in d.guardrails_triggered)

    def test_repeated_failures_switch_retry_to_save_offer(self):
        """The cross-module rule: retry fatigue is priced in, so a customer who keeps failing gets a save offer."""
        def decide(streak, churn):
            passport = {"value_score": 20000, "monthly_revenue": 2499, "payment_health": {"failure_streak": streak}, "churn_risk": churn}
            cands, _ = payment_candidates(attempt(code="do_not_honor", amount=2499), passport, RetryBandit(seed=0), Policy(), NOW, explore=False)
            cands = [c for c in cands if c.action not in ("payment_update_link", "upi_fallback")]   # links already tried
            return cands, kernel().decide(case(amount=2499, passport=passport), cands)
        retry_ev = lambda cands: next(c.ev for c in cands if c.action == "schedule_retry")
        (c1, d1), (c3, d3) = decide(1, 0.1), decide(3, 0.65)
        assert retry_ev(c3) < retry_ev(c1)                       # more failures make another retry less attractive
        assert d3.chosen["action"] == "offer_pause"
        assert "consecutive failures" in d3.reason

    def test_predunning_finds_expiring_cards(self):
        exp = f"{NOW.year}-{NOW.month:02d}"
        m = [PaymentMethod(customer_id="c1", type="card", expiry=exp), PaymentMethod(customer_id="c2", type="card", expiry="2035-01")]
        s = [Subscription(id="s1", customer_id="c1", amount=999), Subscription(id="s2", customer_id="c2", amount=999)]
        out = predunning_targets(m, s, NOW)
        assert [o["customer_id"] for o in out] == ["c1"]

    def test_routing_advice_needs_volume_and_warns_about_tokens(self):
        mk = lambda gw, ok, i: PaymentAttempt(id=f"{gw}{i}", customer_id="c", amount=1, status="succeeded" if ok else "failed", gateway=gw, bank="HDFC", method_type="card", attempted_at=NOW.isoformat())
        atts = [mk("razorpay", i % 10 != 0, i) for i in range(30)] + [mk("stripe", i % 3 != 0, i) for i in range(30)]
        r = routing_advice(atts)
        assert r["advice"][0]["route_to"] == "razorpay" and "not portable" in r["caveat"]


class TestRefundsAndRto:
    def passport(self, **kw):
        return {"value_score": 8000, "trust_score": 95, "serial_abuser": False, "clawback_history": {"refund_rate": 0.0, "refund_count": 0}, "profile": {"email": "a@x.com"}, **kw}

    def test_abuse_score_direction(self):
        legit = abuse_score({"reason": "duplicate_charge", "duplicate_verified": True}, self.passport())
        abuser = abuse_score({"reason": "not_received", "delivered": True, "has_pod": True},
                             self.passport(serial_abuser=True, trust_score=40, clawback_history={"refund_rate": 0.7, "refund_count": 4}))
        assert legit["abuse_probability"] < 0.1 and abuser["abuse_probability"] > 0.9 and abuser["factors"]

    def test_legit_refund_approved_abuser_declined(self):
        req = {"amount": 2000, "reason": "duplicate_charge", "duplicate_verified": True}
        d = kernel().decide(case("refunds", 2000, must_act=True), refund_candidates(req, self.passport(), Policy())[0])
        assert d.chosen["action"] == "approve_refund"
        req = {"amount": 2000, "reason": "not_received", "delivered": True, "has_pod": True}
        bad = self.passport(serial_abuser=True, trust_score=30, clawback_history={"refund_rate": 0.8, "refund_count": 4})
        d = kernel().decide(case("refunds", 2000, must_act=True, passport=bad), refund_candidates(req, bad, Policy())[0])
        assert d.chosen["action"] != "approve_refund" and d.ev > 0

    def test_rto_risk_and_interventions(self):
        risky = {"payment_mode": "COD", "pincode": "781001", "address": "Room 5", "amount": 8000, "order_hour": 2}
        safe = {"payment_mode": "prepaid", "pincode": "560001", "address": "12, MG Road, near Mall, Sector 4", "amount": 800}
        pr, ps = rto_probability(risky, {"prior_rto": 1})["rto_probability"], rto_probability(safe, {"prior_orders": 5})["rto_probability"]
        assert pr > 0.5 > ps
        d = kernel().decide(case("rto", 8000, must_act=True), rto_candidates(risky, {"prior_rto": 1}, Policy())[0])
        assert d.chosen["action"] != "ship_as_is"
        d = kernel().decide(case("rto", 800, must_act=True), rto_candidates(safe, {"prior_orders": 5}, Policy())[0])
        assert d.chosen["action"] == "ship_as_is"


class TestDisputesAndRetention:
    def test_fight_when_odds_good_concede_when_hopeless(self):
        pol = Policy()
        d = kernel().decide(case("clawback", 12000, must_act=True), dispute_candidates(12000, 0.65, False, pol)[0])
        assert d.chosen["action"] == "submit_evidence" and d.mode == "auto"
        d = kernel().decide(case("clawback", 400, must_act=True), dispute_candidates(400, 0.03, False, pol)[0])
        assert d.chosen["action"] == "accept_liability"

    def test_refund_early_beats_fighting_small_ticket_weak_evidence(self):
        pol = Policy()
        cands, meta = dispute_candidates(900, 0.32, True, pol)
        assert kernel().decide(case("clawback", 900, must_act=True), cands).chosen["action"] == "refund_early"
        cands, _ = dispute_candidates(12000, 0.32, True, pol)
        assert kernel().decide(case("clawback", 12000, must_act=True), cands).chosen["action"] == "submit_evidence"
        assert meta["cash_outcomes_inr"]["refund_early"] == -900

    def test_refund_early_only_offered_pre_dispute(self):
        assert "refund_early" not in {c.action for c in dispute_candidates(900, 0.3, False, Policy())[0]}

    def test_deadline_tracker_levels(self):
        now = time.time()
        assert deadline_status(now + 5 * 3600, now)["urgency"] == "critical"
        assert deadline_status(now + 40 * 3600, now)["urgency"] == "high"
        assert deadline_status(now + 9 * 86400, now)["urgency"] == "normal"
        assert deadline_status(now - 100, now)["urgency"] == "overdue"

    def sig(self, **kw):
        base = {"failure_streak": 0, "failures_30d": 0, "days_since_last_success": 5, "usage_decay": 0.0, "unresolved_tickets": 0, "downgrades": 0, "seat_reductions": 0}
        return {**base, **kw}

    def test_churn_split_involuntary_vs_voluntary(self):
        inv = score_churn(self.sig(failure_streak=3, failures_30d=3, days_since_last_success=60))
        vol = score_churn(self.sig(usage_decay=0.9, unresolved_tickets=2, downgrades=1, seat_reductions=1))
        assert inv["type"] == "involuntary" and vol["type"] == "voluntary"
        assert score_churn(self.sig())["score"] < 0.05

    def test_persuadability_excludes_offer_takers_and_loyal(self):
        assert persuadability({"churn_risk": 0.6, "serial_abuser": False, "offers_taken": 3})["verdict"] == "offer_taker"
        assert persuadability({"churn_risk": 0.1, "serial_abuser": False, "offers_taken": 0})["verdict"] == "would_stay"
        assert persuadability({"churn_risk": 0.6, "serial_abuser": True, "offers_taken": 0})["verdict"] == "excluded"
        assert persuadability({"churn_risk": 0.6, "serial_abuser": False, "offers_taken": 0})["verdict"] == "persuadable"

    def test_save_ladder_prefers_payment_fix_for_involuntary(self):
        p = {"churn_risk": 0.7, "churn_type": "involuntary", "monthly_revenue": 2000, "value_score": 40000, "serial_abuser": False, "offers_taken": 0, "trust_score": 90}
        d = kernel().decide(case("retention", 28000, passport=p), retention_candidates(p, Policy()))
        assert d.chosen["action"] in ("payment_update_link", "personal_outreach")
