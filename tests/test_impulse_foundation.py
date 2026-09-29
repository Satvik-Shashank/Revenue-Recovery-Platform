"""Ingestion, decline normalization, identity resolution and the Customer Passport."""

import json
import time

import pytest

from src.impulse.declines import normalize_decline
from src.impulse.identity import IdentityResolver, norm_email, norm_phone
from src.impulse.ingest import IngestionHub, compute_signature
from src.impulse.passport import build_passport, empty_history
from src.impulse.schema import Customer, EngagementEvent, PaymentAttempt, Refund, Dispute

NOW = time.time()


def rz_failed(eid="e1", reason="insufficient_funds", email="a@x.com"):
    return json.dumps({"event": "payment.failed", "id": eid, "created_at": int(NOW), "payload": {"payment": {"entity": {
        "id": "pay_" + eid, "amount": 129900, "currency": "INR", "status": "failed", "method": "card", "email": email,
        "contact": "+919811111111", "error_reason": reason, "card": {"network": "Visa", "last4": "4242", "issuer": "HDFC"},
        "subscription_id": "sub_1"}}}}).encode()


def stripe_failed(eid="evt_1", code="do_not_honor", email="A@x.com"):
    return json.dumps({"id": eid, "type": "payment_intent.payment_failed", "created": int(NOW), "data": {"object": {
        "id": "pi_1", "amount": 129900, "currency": "inr", "customer": "cus_1", "receipt_email": email,
        "last_payment_error": {"decline_code": code, "payment_method": {"card": {"brand": "visa", "fingerprint": "fp_1", "exp_month": 1, "exp_year": 2030}}}}}}).encode()


class TestDeclines:
    @pytest.mark.parametrize("src,raw,code,cat", [
        ("stripe", "insufficient_funds", "insufficient_funds", "soft"), ("stripe", "expired_card", "expired_card", "hard"),
        ("stripe", "authentication_required", "auth_required", "auth"), ("stripe", "issuer_not_available", "bank_downtime", "bank"),
        ("razorpay", "card_expired", "expired_card", "hard"), ("razorpay", "bank_unavailable", "bank_downtime", "bank"),
        ("razorpay", "something with insufficient balance", "insufficient_funds", "soft"), ("stripe", None, "other", "soft"),
    ])
    def test_normalization(self, src, raw, code, cat):
        assert normalize_decline(src, raw) == (code, cat)


class TestIngestion:
    def test_two_gateways_one_schema(self):
        hub = IngestionHub()
        r1, r2 = hub.receive("razorpay", rz_failed()), hub.receive("stripe", stripe_failed())
        a1 = next(e for e in r1["entities"] if isinstance(e, PaymentAttempt))
        a2 = next(e for e in r2["entities"] if isinstance(e, PaymentAttempt))
        assert (a1.gateway, a2.gateway) == ("razorpay", "stripe")
        assert a1.amount == a2.amount == 1299.0 and a1.decline_category == "soft"

    def test_duplicate_delivery_not_double_counted(self):
        hub = IngestionHub()
        assert hub.receive("razorpay", rz_failed())["status"] == "processed"
        assert hub.receive("razorpay", rz_failed())["status"] == "duplicate"
        assert hub.stats["processed"] == 1 and hub.stats["duplicates"] == 1

    def test_signature_verification(self):
        hub = IngestionHub(secrets={"razorpay": "s3cret"})
        body = rz_failed()
        assert hub.receive("razorpay", body)["status"] == "rejected"
        assert hub.receive("razorpay", body, "deadbeef")["status"] == "rejected"
        assert hub.receive("razorpay", body, compute_signature("s3cret", body))["status"] == "processed"

    def test_dead_letter_and_replay_after_fix(self):
        hub = IngestionHub()
        bad = {"event": "payment.failed", "id": "bad1", "payload": {"payment": {"entity": {"id": "pay_x", "currency": "INR"}}}}
        res = hub.receive("razorpay", json.dumps(bad).encode())
        assert res["status"] == "dead_lettered" and len(hub.dead_letters) == 1
        assert hub.replay(res["dead_letter_id"])["status"] == "dead_lettered" and len(hub.dead_letters) == 1
        bad["payload"]["payment"]["entity"]["amount"] = 50000
        assert hub.replay(res["dead_letter_id"], bad)["status"] == "processed" and not hub.dead_letters

    def test_invalid_json_goes_to_dlq(self):
        assert IngestionHub().receive("razorpay", b"{nope")["status"] == "dead_lettered"

    def test_unknown_source_goes_to_dlq(self):
        assert IngestionHub().receive("paypal", b'{"id": 1}')["status"] == "dead_lettered"


class TestIdentity:
    def cust(self, cid, email=None, phone=None, name=None, address=None):
        return Customer(id=cid, email=email, phone=phone, name=name, address=address, source_ids={cid.split(":")[0]: cid})

    def test_email_normalization(self):
        assert norm_email("J.Doe+news@Gmail.com") == "jdoe@gmail.com"
        assert norm_phone("+91 98110-11111") == "9811011111"

    def test_deterministic_merge_across_gateways(self):
        r = IdentityResolver()
        a = r.resolve(self.cust("razorpay:1", email="a@x.com"))
        b = r.resolve(self.cust("stripe:9", email="A@X.com"))
        assert r.canonical("stripe:9") == r.canonical("razorpay:1") == a == b
        assert r.audit[-1]["action"] == "merge" and r.audit[-1]["auto"]

    def test_merge_on_phone_and_fingerprint(self):
        r = IdentityResolver()
        r.resolve(self.cust("razorpay:1", phone="+919811111111"))
        r.resolve(self.cust("stripe:2", phone="9811111111"))
        r.resolve(self.cust("razorpay:3"), fingerprint="fp1")
        r.resolve(self.cust("stripe:4"), fingerprint="fp1")
        assert r.canonical("stripe:2") == r.canonical("razorpay:1")
        assert r.canonical("stripe:4") == r.canonical("razorpay:3")
        assert r.canonical("razorpay:1") != r.canonical("razorpay:3")

    def test_probabilistic_match_is_only_suggested(self):
        r = IdentityResolver()
        r.resolve(self.cust("razorpay:1", name="Aarav Sharma", address="12 MG Road, Sector 4"))
        r.resolve(self.cust("stripe:2", name="Aarav Sharma", address="12 MG Road, Sector 4"))
        assert r.canonical("razorpay:1") != r.canonical("stripe:2")
        assert r.suggestions and r.suggestions[0]["score"] >= 0.8
        r.merge("razorpay:1", "stripe:2")
        assert r.canonical("razorpay:1") == r.canonical("stripe:2")

    def test_unmerge_restores_identity(self):
        r = IdentityResolver()
        r.resolve(self.cust("razorpay:1", email="a@x.com"))
        r.resolve(self.cust("stripe:2", email="a@x.com"))
        r.unmerge(r.audit[-1]["id"])
        assert r.canonical("stripe:2") != r.canonical("razorpay:1")
        assert r.audit[-1]["action"] == "unmerge"


def _passport(hist, now=NOW):
    return build_passport("c1", {"id": "c1", "email": "a@x.com"}, hist, now)


def _fail(i, days_ago, amount=1000, code="do_not_honor"):
    return PaymentAttempt(id=f"f{i}", customer_id="c1", amount=amount, status="failed", decline_code=code, decline_category="soft",
                          attempted_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - days_ago * 86400)), gateway="razorpay")


class TestPassport:
    def test_failure_streak_raises_churn(self):
        clean, bad = empty_history(), empty_history()
        bad["attempts"] = [_fail(1, 20), _fail(2, 10), _fail(3, 1)]
        assert _passport(bad)["churn_risk"] > _passport(clean)["churn_risk"]
        assert _passport(bad)["payment_health"]["failure_streak"] == 3

    def test_serial_refunder_flagged_and_trust_drops(self):
        h = empty_history()
        h["attempts"] = [PaymentAttempt(id=f"o{i}", customer_id="c1", amount=1000, status="succeeded", attempted_at="2026-01-01T00:00:00+00:00", gateway="razorpay") for i in range(5)]
        h["refunds"] = [Refund(id=f"r{i}", customer_id="c1", amount=1000, requested_at="2026-02-01T00:00:00+00:00", status="processed") for i in range(4)]
        p = _passport(h)
        assert p["serial_abuser"] and p["trust_score"] < 70

    def test_two_disputes_flag_abuser(self):
        h = empty_history()
        h["disputes"] = [Dispute(id=f"d{i}", customer_id="c1", amount=500, opened_at="2026-01-01T00:00:00+00:00") for i in range(2)]
        assert _passport(h)["serial_abuser"]

    def test_fusion_needs_three_simultaneous_signals(self):
        h = empty_history()
        iso = lambda d: time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - d * 86400))
        h["attempts"] = [_fail(1, 1)]
        h["refunds"] = [Refund(id="r1", customer_id="c1", amount=900, requested_at=iso(2))]
        assert _passport(h)["fusion"] is None
        h["engagement"] = [EngagementEvent(customer_id="c1", type="ticket", timestamp=iso(3))]
        f = _passport(h)["fusion"]
        assert f and f["recommendation"] == "personal_outreach" and len(f["signals"]) == 3
