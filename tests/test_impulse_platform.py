"""Ledger, Replay Lab, Leak Audit, Billing, the engine end to end, and the HTTP API."""

import json
import os
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.impulse import audit, billing
from src.impulse.engine import ImpulseEngine
from src.impulse.ledger import Ledger
from src.impulse.schema import Dispute, Order, PaymentAttempt, Refund, Shipment, Subscription
from src.impulse.sim import generate_world, policy_baseline, policy_rules, run_replay, true_retry_p
from src.impulse.narrative import answer_question, customer_message, evidence_narrative


class TestLedger:
    def make(self):
        led = Ledger(fee_pct=10, min_holdout=5)
        for i in range(20):
            led.record(case_id=f"h{i}", module="payments", action="merchant_baseline", amount_at_stake=1000, recovered=1000 if i < 6 else 0, arm="holdout")
        for i in range(20):
            led.record(case_id=f"t{i}", module="payments", action="recovery_journey", amount_at_stake=1000, recovered=1000 if i < 12 else 0, cost=2, arm="treatment")
        return led

    def test_hash_chain_detects_tampering(self):
        led = self.make()
        assert led.verify_chain()["valid"]
        led.entries[10]["recovered"] = 999999
        v = led.verify_chain()
        assert not v["valid"] and v["broken_at"] == 11

    def test_only_incremental_revenue_over_holdout_baseline_is_credited(self):
        s = self.make().summary()["by_module"]["payments"]
        assert s["baseline_basis"] == "holdout" and s["baseline_rate"] == 0.3
        assert s["gross_recovered"] == 12000 and s["baseline_expected"] == 6000
        assert s["incremental"] == 6000 and s["net"] == 6000 - 40

    def test_fee_only_on_net_incremental(self):
        s = self.make().summary()
        assert s["impulse_fee"] == round(s["net_incremental"] * 0.10, 2) and s["merchant_net_gain"] == round(s["net_incremental"] - s["impulse_fee"], 2)
        empty = Ledger()
        empty.record(case_id="x", module="payments", action="a", amount_at_stake=1000, recovered=0, cost=50)
        assert empty.summary()["impulse_fee"] == 0

    def test_assumed_baseline_until_enough_holdout(self):
        led = Ledger(min_holdout=50)
        led.record(case_id="h", module="payments", action="b", amount_at_stake=100, recovered=100, arm="holdout")
        assert led.baseline_rate("payments")[1] == "assumed"

    def test_csv_export(self):
        assert self.make().to_csv().splitlines()[0].startswith("seq,time,case_id")


class TestReplayLab:
    def test_ground_truth_has_structure_policies_cannot_see(self):
        w = generate_world(1, 10)[0]
        assert true_retry_p("expired_card", w["fail_dt"], w["fail_dt"]) == 0.0
        from datetime import timedelta
        d = w["fail_dt"].replace(day=2)
        assert true_retry_p("insufficient_funds", d, d + timedelta(days=30)) > 0.1

    def test_common_random_numbers_make_policies_comparable(self):
        w1, w2 = generate_world(5, 50), generate_world(5, 50)
        assert [c["u_retry"] for c in w1] == [c["u_retry"] for c in w2]
        assert [policy_baseline(c)["ok"] for c in w1] == [policy_baseline(c)["ok"] for c in w2]

    def test_impulse_beats_merchant_baseline_with_interval_and_attribution_is_close(self):
        r = run_replay(n=350, seeds=3)
        lift = r["lift"]["recovery_rate_pts"]
        assert lift["lo"] > 0 and r["policies"]["impulse"]["recovery_rate"]["mean"] > r["policies"]["baseline"]["recovery_rate"]["mean"]
        ac = r["attribution_check"]
        assert abs(ac["ledger_estimated_incremental_inr"] - ac["true_incremental_inr"]) < 0.5 * abs(ac["true_incremental_inr"])
        assert "Simulated world" in r["disclosure"]
        assert r["policies"]["impulse"]["retries_per_recovery"] < r["policies"]["baseline"]["retries_per_recovery"]


class TestAudit:
    def test_auto_map_handles_awkward_column_names(self):
        df = audit.sample_audit_data()["payments"]
        m = audit.auto_map(df, "payments")
        assert m["amount"]["column"] == "Txn Amount" and m["decline_code"]["column"] == "Error Reason" and m["status"]["column"] == "Payment Status"

    def test_manual_mapping_override(self):
        df = pd.DataFrame({"weird_a": ["failed", "captured"], "weird_b": [100, 200]})
        out, used, problems = audit.apply_mapping(df, "payments", {"status": "weird_a", "amount": "weird_b"})
        assert used["status"] == "weird_a" and len(out) == 2 and not problems

    def test_missing_required_field_reported(self):
        _, _, problems = audit.apply_mapping(pd.DataFrame({"foo": [1]}), "payments", None)
        assert any("amount" in p for p in problems)

    def test_report_headline_and_causes(self):
        rep = audit.run_audit(audit.sample_audit_data())
        assert rep["headline"].startswith("You leaked ₹") and rep["total_leak"] > rep["estimated_recoverable"] > 0
        assert set(rep["by_cause"]) == {"failed", "clawed_back", "stopped", "missed"}
        assert rep["sample_customers"] and "disclosure" in rep and "<html" in audit.render_report_html(rep)

    def test_observed_recovery_used_when_order_ids_present(self):
        pay = pd.DataFrame({"amount": [100, 100, 100, 100], "status": ["failed", "captured", "failed", "failed"], "order_id": ["a", "a", "b", "c"]})
        rep = audit.run_audit({"payments": pay})
        assert any("observed" in f["text"] and "33%" in f["text"] for f in rep["top_findings"])

    def test_html_report_escapes_input(self):
        rep = audit.run_audit(audit.sample_audit_data())
        rep["sample_customers"][0]["customer"] = "<script>alert(1)</script>"
        assert "<script>alert(1)</script>" not in audit.render_report_html(rep)


class TestBilling:
    def test_planted_errors_are_found(self):
        d = billing.demo_billing_data(seed=7)
        checks = {f["check"] for f in billing.run_assurance(d["contracts"], d["invoices"], d["usage"], d["seats"], d["credits"], d["payments"], d["today"])}
        assert {"contract_vs_invoice", "expired_discount", "usage_vs_billing", "seat_mismatch", "duplicate_credit", "unjustified_credit", "paid_without_payment"} <= checks

    def test_worklist_ranks_by_value_times_likelihood_and_flags_msme(self):
        d = billing.demo_billing_data(seed=7)
        work = billing.collections_worklist(d["open_invoices"], billing.LatenessModel().fit(d["paid_history"]), d["today"])
        assert work == sorted(work, key=lambda r: -r["priority_inr"])
        assert all(w["msme_45_day_flag"] == (w["days_overdue"] > 45) for w in work)

    def test_promise_tracking(self):
        t = billing.PromiseTracker()
        p = t.log("INV1", "Acme", 1000, "2020-01-01")
        assert t.due_followups(billing._d("2026-01-01"))
        t.mark(p["id"], False)
        assert t.reliability()["broken"] == 1


def rz(eid, amount, reason, email="p@x.com", sub="sub_p"):
    return json.dumps({"event": "payment.failed", "id": eid, "created_at": int(time.time()), "payload": {"payment": {"entity": {
        "id": "pay_" + eid, "amount": int(amount * 100), "currency": "INR", "status": "failed", "method": "card", "email": email, "contact": "+919800000009",
        "error_reason": reason, "subscription_id": sub, "card": {"network": "Visa", "issuer": "HDFC"}}}}}).encode()


@pytest.fixture()
def engine():
    return ImpulseEngine(seed=1)


class TestEngine:
    def test_failed_payment_flows_to_decision_action_and_ledger(self, engine):
        r = engine.ingest("razorpay", rz("e1", 1299, "insufficient_funds"))
        rec = engine.cases[r["cases"][0]]
        assert rec["decision"]["chosen"]["action"] == "schedule_retry" and rec["status"] in ("active", "holdout")
        assert rec["journey"] and engine.overview()["headline"].startswith("You are leaking")
        engine.simulate_pending()                      # follow the recovery chain to its end (a failed step opens a follow-up)
        assert engine.ledger.entries and engine.ledger.verify_chain()["valid"]

    def test_hard_decline_is_never_retried(self, engine):
        r = engine.ingest("razorpay", rz("e2", 2999, "card_expired"))
        rec = engine.cases[r["cases"][0]]
        assert rec["decision"]["chosen"]["action"] != "schedule_retry"
        assert any(g["guardrail"] == "no_retry_hard_decline" for g in rec["decision"]["guardrails_triggered"])

    def test_failed_step_triggers_follow_up_and_one_ledger_row_per_chain(self, engine):
        r = engine.ingest("razorpay", rz("e3", 1299, "expired_card", email="chain@x.com", sub="sub_chain"))
        first = r["cases"][0]
        for _ in range(8):
            open_cases = [c for c in engine.cases.values() if c["status"] in ("active", "holdout")]
            if not open_cases:
                break
            for c in open_cases:
                engine.resolve_case(c["case_id"], {"success": False, "recovered": 0, "cost": 1, "source": "test"})
        assert len([e for e in engine.ledger.entries if e["module"] == "payments"]) == 1
        assert engine.ledger.entries[0]["case_id"] == first and engine.ledger.entries[0]["recovered"] == 0

    def test_real_success_webhook_closes_the_case_with_real_outcome(self, engine):
        r = engine.ingest("razorpay", rz("e4", 1299, "insufficient_funds", email="s@x.com", sub="sub_s"))
        ok = json.loads(rz("e5", 1299, "x", email="s@x.com", sub="sub_s"))
        ok["event"], ok["payload"]["payment"]["entity"]["status"] = "payment.captured", "captured"
        engine.ingest("razorpay", json.dumps(ok).encode())
        rec = engine.cases[r["cases"][0]]
        assert rec["status"] == "resolved" and rec["outcome"]["success"] and not rec["outcome"]["simulated"]

    def test_same_customer_across_gateways_resolves_once(self, engine):
        engine.ingest("razorpay", rz("e6", 1299, "insufficient_funds", email="meera@x.com"))
        engine.ingest("stripe", json.dumps({"id": "evt_9", "type": "payment_intent.payment_failed", "created": int(time.time()), "data": {"object": {
            "id": "pi_9", "amount": 129900, "currency": "inr", "customer": "cus_m", "receipt_email": "Meera@X.com",
            "last_payment_error": {"decline_code": "do_not_honor", "payment_method": {"card": {"brand": "visa", "fingerprint": "fp9"}}}}}}).encode())
        assert len(engine.history) == 1
        assert {a.gateway for a in next(iter(engine.history.values()))["attempts"]} == {"razorpay", "stripe"}

    def test_approval_flow_approve_edit_reject(self, engine):
        def dispute(i, amount):
            d = Dispute(id=f"D{i}", customer_id=f"custom:{i}", network="Visa", amount=amount, opened_at="2026-09-01T00:00:00+00:00", respond_by="2026-10-30T00:00:00+00:00")
            return engine.add_dispute(d, {"delivered": True, "has_delivery_proof": True, "ip_geolocation_match": True, "avs_cvv_match": "both_match", "has_3ds_authentication": True})
        rec = dispute(1, 60000)                       # above the auto limit
        assert rec["status"] == "pending_approval" and f"apr_{rec['case_id']}" in engine.approvals
        assert engine.decide_approval(f"apr_{rec['case_id']}", "approve")["status"] == "approved" and engine.cases[rec["case_id"]]["status"] == "active"
        with pytest.raises(ValueError):
            engine.decide_approval(f"apr_{rec['case_id']}", "reject")
        rec2 = dispute(2, 70000)
        assert engine.decide_approval(f"apr_{rec2['case_id']}", "edit", "accept_liability")["edited_to"] == "accept_liability"
        assert engine.cases[rec2["case_id"]]["decision"]["chosen"]["action"] == "accept_liability"
        rec3 = dispute(3, 80000)
        engine.decide_approval(f"apr_{rec3['case_id']}", "reject")
        assert engine.cases[rec3["case_id"]]["status"] == "rejected"
        assert any(a["event"].startswith("approval:") for a in engine.audit_log)

    def test_policy_change_takes_effect(self, engine):
        engine.policy.update({"autonomy": {"payments": "recommend"}, "action_overrides": {"schedule_retry": "recommend"}})
        r = engine.ingest("razorpay", rz("e7", 1299, "insufficient_funds"))
        assert engine.cases[r["cases"][0]]["status"] in ("recommended", "holdout")

    def test_action_is_idempotent_and_reversible(self, engine):
        r = engine.ingest("razorpay", rz("e8", 2999, "card_expired", email="i@x.com", sub="sub_i"))
        rec = engine.cases[r["cases"][0]]
        if rec["status"] == "active":
            a = engine.actions.records[rec["action_id"]]
            assert engine.actions.execute(rec["_case"], type("D", (), {"chosen": rec["decision"]["chosen"], "id": "x"})())["id"] == a["id"]
            assert engine.actions.undo(a["id"])["status"] == "reversed"

    def test_outbound_webhooks_queue_events(self, engine):
        engine.ingest("razorpay", rz("e9", 1299, "insufficient_funds"))
        assert any(o["event"] == "decision.created" for o in engine.outbox)

    def test_refund_request_scores_against_history(self, engine):
        from src.impulse.demo import silent
        r = engine.ingest("razorpay", rz("e10", 1299, "insufficient_funds", email="serial@x.com"))
        cid = next(iter(engine.history))
        silent(engine, [Order(id="o1", customer_id=cid, amount=3000, created_at="2026-08-01T00:00:00+00:00"), Shipment(order_id="o1", delivered_at="2026-08-05T00:00:00+00:00", pod=True)])
        recs = engine.apply_entities([Refund(id="rf1", customer_id=cid, amount=3000, reason="not received", requested_at="2026-09-01T00:00:00+00:00")])
        refund_case = next(c for c in recs if c["module"] == "refunds")
        assert refund_case["meta"]["abuse_probability"] > 0.4 and refund_case["decision"]["chosen"]["action"] != "approve_refund"


class TestNarrative:
    def test_language_layer_works_without_llm(self, engine):
        assert answer_question("how much did we recover?", engine.ledger, engine)["source"] == "ledger"
        assert customer_message("x", None)["source"] == "none"
        pack = {"items": [{"label": "POD", "present": True, "role": "compelling"}, {"label": "3DS", "present": False, "role": "compelling"}], "completeness": 0.5}
        n = evidence_narrative({"dispute_id": "D1", "dispute_amount": 100}, {"classification": {"predicted_reason_code": "13.1"}}, pack)
        assert n["source"] == "template" and "POD" in n["text"] and "3DS" in n["text"]


@pytest.fixture(scope="module")
def client():
    os.environ["IMPULSE_EMPTY"] = "1"
    from api.index import app
    from src.impulse.routes import reset_engine
    reset_engine(empty=True)
    return TestClient(app)


class TestApi:
    def test_webhook_flow_and_console_endpoints(self, client):
        r = client.post("/api/impulse/webhooks/razorpay", content=rz("api1", 1299, "insufficient_funds"))
        assert r.status_code == 200 and r.json()["status"] == "processed"
        assert client.post("/api/impulse/webhooks/razorpay", content=rz("api1", 1299, "insufficient_funds")).json()["status"] == "duplicate"
        for path in ("overview", "payments", "retention", "clawback", "billing", "approvals", "ledger", "policy", "customers", "connections", "identity", "replay-lab", "audit-log"):
            assert client.get(f"/api/impulse/{path}").status_code == 200, path

    def test_signature_enforced_when_secret_set(self, client):
        client.put("/api/impulse/connections/secret", json={"source": "stripe", "secret": "abc"})
        assert client.post("/api/impulse/webhooks/stripe", content=b"{}").status_code == 401
        client.put("/api/impulse/connections/secret", json={"source": "stripe", "secret": None})

    def test_policy_validation_over_http(self, client):
        assert client.put("/api/impulse/policy", json={"holdout_pct": 99}).status_code == 400
        assert client.put("/api/impulse/policy", json={"fee_pct": 15}).json()["fee_pct"] == 15

    def test_dispute_endpoint_uses_real_models(self, client):
        r = client.post("/api/impulse/clawback/disputes", json={"dispute_id": "T1", "dispute_amount": 12499, "delivery_confirmed": True, "has_delivery_proof": True,
                                                                "ip_geolocation_match": True, "avs_cvv_match": "both_match", "has_3ds_authentication": True, "customer_prior_orders": 3})
        j = r.json()
        assert r.status_code == 200 and j["decision"]["chosen"]["action"] == "submit_evidence" and j["evidence_pack"]["items"] and j["narrative"]["text"]

    def test_audit_upload_and_report(self, client):
        frames = audit.sample_audit_data()
        files = {k: (f"{k}.csv", frames[k].to_csv(index=False), "text/csv") for k in ("payments", "disputes")}
        r = client.post("/api/impulse/audit/upload", files=files)
        assert r.status_code == 200 and r.json()["report"]["headline"]
        assert client.get(f"/api/impulse/audit/{r.json()['session']}/report").status_code == 200
        assert client.post("/api/impulse/audit/upload", files={}).status_code == 400

    def test_unknown_resources_404(self, client):
        assert client.get("/api/impulse/cases/nope").status_code == 404
        assert client.get("/api/impulse/customers/nope").status_code == 404
        assert client.post("/api/impulse/dead-letters/nope/replay").status_code == 404

    def test_ledger_export_and_verify(self, client):
        assert client.get("/api/impulse/ledger/export.csv").status_code == 200
        assert client.get("/api/impulse/ledger/verify").json()["valid"]

    def test_hosted_pages(self, client):
        r = client.post("/api/impulse/webhooks/razorpay", content=rz("api2", 999, "card_expired", email="h@x.com", sub="sub_h"))
        cid = r.json()["cases"][0]
        v = client.get(f"/api/impulse/hosted/{cid}").json()
        assert v["page"] in ("payment_update", "pause_or_downgrade") and client.get("/api/impulse/hosted/bad").status_code == 404


class TestPlaygrounds:
    def test_try_payment_decisions_differ_by_reason(self, client):
        soft = client.post("/api/impulse/try/payment", json={"reason": "insufficient_funds", "amount": 1299}).json()
        hard = client.post("/api/impulse/try/payment", json={"reason": "card_expired", "amount": 2999}).json()
        assert soft["decision"]["chosen"]["action"] == "schedule_retry" and soft["journey"]
        assert hard["decision"]["chosen"]["action"] != "schedule_retry"

    def test_try_payment_validation(self, client):
        assert client.post("/api/impulse/try/payment", json={"reason": "insufficient_funds", "amount": -5}).status_code == 422

    def test_billing_check_finds_and_clears(self, client):
        bad = client.post("/api/impulse/billing/check", json={"contract_price": 60000, "billed": 50000, "active_seats": 14, "billed_seats": 10, "seat_price": 1200}).json()
        assert bad["total"] == 10000 + 4800 and {f["check"] for f in bad["findings"]} == {"contract_vs_invoice", "seat_mismatch"}
        ok = client.post("/api/impulse/billing/check", json={"contract_price": 50000, "billed": 50000, "active_seats": 10, "billed_seats": 10}).json()
        assert ok["findings"] == [] and ok["total"] == 0
