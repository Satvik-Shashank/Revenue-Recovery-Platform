"""Deterministic demo world: 56 days of synthetic merchant history plus scripted showcase scenarios.

Everything flows through the same code paths as production (adapters -> identity -> passport -> Kernel).
The data is synthetic and says so in the UI."""

import json
import random
from datetime import datetime, timedelta, timezone

from .engine import ImpulseEngine
from .schema import (Customer, Dispute, EngagementEvent, Order, PaymentAttempt, PaymentMethod, Refund, Shipment,
                     Subscription)
from .sim import MIX

FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Rahul", "Karan", "Neha", "Ananya", "Diya", "Meera", "Rohit", "Sanjay", "Pooja", "Kiran",
         "Arjun", "Sneha", "Vikas", "Tanvi", "Nikhil", "Riya", "Manish", "Shreya", "Harsh", "Isha", "Yash", "Nandini", "Gaurav", "Simran"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Gupta", "Mehta", "Reddy", "Patel", "Singh", "Kapoor", "Joshi", "Menon", "Das", "Bose", "Khan", "Rao"]
BANKS = ["HDFC", "ICICI", "SBI", "Axis", "Kotak", "Yes"]
PINS = ["110001", "400001", "560001", "600001", "700001", "780001", "800001", "190001", "302001", "500001"]
ADDR = ["12, MG Road, near City Mall, Sector 4", "Flat 3B, Lake View Apts, Andheri East, Mumbai", "H.No 44 opp. Temple, Gandhi Nagar",
        "Plot 9, Green Colony, Behind Bus Stand", "Room 5"]


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def sample_events(now: float | None = None) -> dict:
    """Recorded-style webhook payloads for the live 'neutrality' demo: same customer, two gateways."""
    now = int(now or datetime.now(timezone.utc).timestamp())
    rz = lambda eid, email, phone, amt, reason, ev="payment.failed": {
        "event": ev, "id": eid, "created_at": now, "payload": {"payment": {"entity": {
            "id": "pay_" + eid, "amount": int(amt * 100), "currency": "INR", "status": "failed", "method": "card", "email": email,
            "contact": phone, "error_reason": reason, "created_at": now, "subscription_id": "sub_" + email.split("@")[0],
            "card": {"network": "Visa", "last4": "4242", "issuer": "HDFC", "expiry_month": 12, "expiry_year": 2027}}}}}
    return {
        "razorpay_soft_decline": {"source": "razorpay", "label": "Razorpay: soft decline (insufficient funds)",
                                  "event": rz(f"rz_{now}_1", "meera.demo@example.com", "+919800000001", 1499, "insufficient_funds")},
        "razorpay_hard_decline": {"source": "razorpay", "label": "Razorpay: hard decline (card expired)",
                                  "event": rz(f"rz_{now}_2", "arjun.demo@example.com", "+919800000002", 2999, "card_expired")},
        "stripe_same_customer": {"source": "stripe", "label": "Stripe: same customer as the Razorpay event, different gateway",
                                 "event": {"id": f"evt_{now}_3", "type": "payment_intent.payment_failed", "created": now, "data": {"object": {
                                     "id": f"pi_{now}", "amount": 149900, "currency": "inr", "customer": "cus_meera", "receipt_email": "Meera.Demo@example.com",
                                     "metadata": {"phone": "+91 98000 00001", "recurring": "1", "bank": "HDFC"},
                                     "last_payment_error": {"decline_code": "do_not_honor", "payment_method": {"card": {"brand": "visa", "fingerprint": "fp_meera", "exp_month": 12, "exp_year": 2027}}}}}}},
        "stripe_dispute": {"source": "stripe", "label": "Stripe: dispute opened",
                           "event": {"id": f"evt_{now}_4", "type": "charge.dispute.created", "created": now, "data": {"object": {
                               "id": f"dp_{now}", "amount": 899900, "payment_intent": f"pi_{now}", "customer": "cus_meera", "reason": "fraudulent",
                               "network": "visa", "evidence_details": {"due_by": now + 7 * 86400}}}}},
        "malformed_event": {"source": "razorpay", "label": "Malformed event (goes to the dead-letter queue)",
                            "event": {"event": "payment.failed", "id": f"rz_{now}_bad", "payload": {"payment": {"entity": {"id": "pay_bad", "currency": "INR"}}}}},
    }


class DemoBuilder:
    def __init__(self, engine: ImpulseEngine, seed: int = 7):
        self.e = engine
        self.rng = random.Random(seed)
        self.custs: list[dict] = []
        self.n_att = 0

    def _name(self):
        return f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"

    def make_customers(self, n: int, start_ts: float):
        for i in range(n):
            src = self.rng.choice(["razorpay", "razorpay", "stripe"])
            name = self._name()
            email = f"{name.lower().replace(' ', '.')}{i}@example.in"
            cid = f"{src}:cust_{i}"
            sub = self.rng.random() < 0.72
            amount = self.rng.choice([499, 999, 1299, 1999, 2499, 4999])
            bank = self.rng.choice(BANKS)
            exp_soon = self.rng.random() < 0.08
            exp = datetime.fromtimestamp(start_ts + (56 + (self.rng.randint(2, 25) if exp_soon else self.rng.randint(120, 900))) * 86400, timezone.utc)
            fp = f"fp_{i}"
            ents = [Customer(source=src, id=cid, name=name, email=email, phone=f"+9198{self.rng.randint(10000000, 99999999)}",
                             source_ids={src: f"cust_{i}"}, created_at=_iso(start_ts - self.rng.randint(20, 400) * 86400), address=self.rng.choice(ADDR)),
                    PaymentMethod(source=src, customer_id=cid, type="card", network=self.rng.choice(["Visa", "Mastercard"]), bank=bank,
                                  fingerprint=fp, expiry=f"{exp.year}-{exp.month:02d}")]
            if sub:
                ents.append(Subscription(source=src, id=f"sub_{i}", customer_id=cid, plan="pro", amount=amount, status="active",
                                         next_billing_at=_iso(start_ts + 70 * 86400)))
            self.e.apply_entities(ents)
            self.custs.append({"id": cid, "src": src, "sub": sub, "amount": amount, "bank": bank, "fp": fp, "i": i,
                               "root": self.e.resolver.canonical(cid)})
            # a healthy payment history (also feeds routing advice)
            for k in range(self.rng.randint(1, 3)):
                for gw in {src, self.rng.choice(["razorpay", "stripe"])}:
                    self.e.hist(cid)["attempts"].append(PaymentAttempt(
                        source=gw, id=f"hist_{i}_{k}_{gw}", customer_id=self.e.resolver.canonical(cid), amount=amount, status="succeeded",
                        gateway=gw, method_type="card", bank=bank, attempted_at=_iso(start_ts - (k + 1) * 30 * 86400), is_recurring=sub))

    def fail(self, c: dict, when: float, code: str | None = None):
        from .declines import CATEGORY
        codes, w = zip(*MIX)
        code = code or self.rng.choices(codes, w)[0]
        self.n_att += 1
        gw = self.rng.choice(["razorpay", "razorpay", "stripe"])
        a = PaymentAttempt(source=gw, id=f"f_{self.n_att}", customer_id=c["root"], amount=c["amount"] if c["sub"] else self.rng.choice([799, 1499, 3499, 8999]),
                           status="failed", decline_code=code, decline_category=CATEGORY[code], raw_decline_code=code, gateway=gw, method_type="card",
                           bank=c["bank"], attempted_at=_iso(when), is_recurring=c["sub"], subscription_id=f"sub_{c['i']}" if c["sub"] else None,
                           fingerprint=c["fp"])
        return self.e.apply_entities([a])

    def history_days(self, days: int):
        e = self.e
        end = e.now()
        for d in range(days, 0, -1):
            t = end - d * 86400 + 9 * 3600
            e.set_clock(t)
            for _ in range(self.rng.choice([3, 4, 5, 6])):
                self.fail(self.rng.choice(self.custs), t + self.rng.random() * 8 * 3600)
            if self.rng.random() < 0.28:
                self._dispute(t)
            for _ in range(self.rng.choice([0, 1, 2])):
                self._refund(t)
            for _ in range(self.rng.choice([0, 1, 2])):
                self._order(t)
            if self.rng.random() < 0.6:
                self._decay(t)
            e.set_clock(t + 3 * 86400)      # outcomes arrive ~3 days later
            for cid, rec in list(e.cases.items()):
                if rec["status"] in ("active", "holdout") and e.now() - rec["created_at"] >= 2.5 * 86400:
                    e.resolve_case(cid)
            for apr in [a for a in e.approvals.values() if a["status"] == "pending" and e.now() - a["created_at"] > 1.5 * 86400]:
                e.decide_approval(apr["id"], "approve", actor="auto-demo")
        e.set_clock(None)

    def _dispute(self, t: float):
        c = self.rng.choice(self.custs)
        strong = self.rng.random() < 0.55
        amt = round(self.rng.lognormvariate(7.8, 0.8), 2)
        did = f"dsp_{self.n_att}_{self.rng.randint(1000, 9999)}"
        root = c["root"]
        oid = f"ord_{did}"
        self.e.apply_entities([Order(id=oid, customer_id=root, items=[{"category": self.rng.choice(["electronics", "apparel", "software"]), "shipping": "express"}],
                                     amount=amt, payment_mode="prepaid", created_at=_iso(t - 15 * 86400), delivery_status="delivered"),
                               Shipment(order_id=oid, carrier="Delhivery", delivered_at=_iso(t - 10 * 86400), pod=strong)])
        d = Dispute(id=did, customer_id=root, network=self.rng.choice(["Visa", "Mastercard"]), amount=amt, opened_at=_iso(t),
                    respond_by=_iso(t + 10 * 86400), reason_code=self.rng.choice(["fraud", "not_received", "not_as_described"]),
                    pre_dispute=self.rng.random() < 0.2)
        self.e.add_dispute(d, {"delivered": True, "has_delivery_proof": strong, "ip_geolocation_match": self.rng.random() < (0.8 if strong else 0.3),
                               "avs_cvv_match": self.rng.choice(["both_match", "neither", "avs_only"]) if strong else "neither",
                               "has_3ds_authentication": strong and self.rng.random() < 0.6, "account_age_days": self.rng.randint(5, 700),
                               "prior_orders": self.rng.randint(0, 9), "transaction_at": t - 15 * 86400})

    def _refund(self, t: float):
        c = self.rng.choice(self.custs)
        root = c["root"]
        oid = f"ord_r_{self.rng.randint(0, 10**9)}"
        pod = self.rng.random() < 0.6
        amt = round(self.rng.lognormvariate(7.2, 0.7), 2)
        self.e.apply_entities([Order(id=oid, customer_id=root, items=[{"category": "apparel"}], amount=amt, created_at=_iso(t - 9 * 86400)),
                               Shipment(order_id=oid, carrier="BlueDart", delivered_at=_iso(t - 6 * 86400), pod=pod),
                               Refund(id=f"rf_{oid}", customer_id=root, amount=amt, requested_at=_iso(t),
                                      reason=self.rng.choice(["not received", "not as described", "changed mind", "defective"]))])

    def _order(self, t: float):
        c = self.rng.choice(self.custs)
        self.e.apply_entities([Order(id=f"cod_{self.rng.randint(0, 10**9)}", customer_id=c["root"], amount=self.rng.choice([799, 1499, 2999, 6499, 8999]),
                                     payment_mode=self.rng.choice(["COD", "COD", "prepaid"]), pincode=self.rng.choice(PINS), address=self.rng.choice(ADDR),
                                     created_at=_iso(t + self.rng.randint(0, 20) * 3600), items=[{"category": "apparel"}])])

    def _decay(self, t: float):
        c = self.rng.choice(self.custs)
        if not c["sub"]:
            return
        for j in range(self.rng.randint(1, 3)):
            self.e.apply_entities([EngagementEvent(customer_id=c["root"], type="usage", timestamp=_iso(t - j * 86400), value=self.rng.randint(1, 6))])
        if self.rng.random() < 0.12:
            self.e.apply_entities([EngagementEvent(customer_id=c["root"], type=self.rng.choice(["ticket", "downgrade", "seat_reduction"]), timestamp=_iso(t))])


def silent(e: ImpulseEngine, entities: list):
    """Load background history WITHOUT triggering decisions (the past already happened)."""
    for x in entities:
        h = e.hist(x.customer_id) if hasattr(x, "customer_id") else None
        if isinstance(x, PaymentAttempt):
            e.payment_index[x.id] = x.customer_id
            h["attempts"].append(x)
        elif isinstance(x, Order):
            e.order_index[x.id] = x.customer_id
            h["orders"].append(x)
        elif isinstance(x, Shipment):
            e.hist(e.order_index[x.order_id])["shipments"].append(x)
        elif isinstance(x, Refund):
            h["refunds"].append(x)
        elif isinstance(x, EngagementEvent):
            h["engagement"].append(x)
            if x.type == "offer_taken":
                h["offers_taken"] += 1
        elif isinstance(x, Subscription):
            h["subscriptions"].append(x)
        elif isinstance(x, PaymentMethod):
            h["methods"].append(x)


# ── scripted showcase scenarios (present-day, left open) ─────────────────────

def scripted_scenarios(e: ImpulseEngine):
    now = e.now()
    events = sample_events(now)
    out = {}
    # 1 + 2: same customer arrives from two gateways and is resolved to ONE identity
    r1 = e.ingest("razorpay", json.dumps(events["razorpay_soft_decline"]["event"]).encode())
    r2 = e.ingest("stripe", json.dumps(events["stripe_same_customer"]["event"]).encode())
    out["neutrality"] = {"razorpay": r1, "stripe": r2}
    e.ingest("razorpay", json.dumps(events["razorpay_hard_decline"]["event"]).encode())
    e.ingest("razorpay", json.dumps(events["malformed_event"]["event"]).encode())      # -> dead-letter queue

    def cust(cid, name, email, phone, src="razorpay", created_days=300, address="12, MG Road, near City Mall, Sector 4"):
        e.apply_entities([Customer(source=src, id=f"{src}:{cid}", name=name, email=email, phone=phone, source_ids={src: cid},
                                   created_at=_iso(now - created_days * 86400), address=address)])
        return e.resolver.canonical(f"{src}:{cid}")

    # 3. Rohan: repeated failures, unresolved ticket, decaying usage -> retry becomes a pause offer
    rohan = cust("rohan", "Rohan Mehta", "rohan.mehta@example.in", "+919822222222")
    silent(e, [PaymentMethod(source="razorpay", customer_id=rohan, type="card", network="Visa", bank="SBI", fingerprint="fp_rohan", expiry="2027-08"),
                      Subscription(source="razorpay", id="sub_rohan", customer_id=rohan, plan="team", amount=2499, next_billing_at=_iso(now + 5 * 86400))])
    for d in range(60, 30, -3):
        silent(e, [EngagementEvent(customer_id=rohan, type="usage", timestamp=_iso(now - d * 86400), value=6)])
    for days in (75, 45):
        silent(e, [PaymentAttempt(source="razorpay", id=f"ok_rohan_{days}", customer_id=rohan, amount=2499, status="succeeded", gateway="razorpay",
                                         bank="SBI", attempted_at=_iso(now - days * 86400), is_recurring=True, subscription_id="sub_rohan")])
    silent(e, [EngagementEvent(customer_id=rohan, type="ticket", timestamp=_iso(now - 9 * 86400))])
    for days in (21, 9):
        silent(e, [PaymentAttempt(source="razorpay", id=f"fail_rohan_{days}", customer_id=rohan, amount=2499, status="failed", decline_code="do_not_honor",
                                         decline_category="soft", raw_decline_code="do_not_honor", gateway="razorpay", bank="SBI",
                                         attempted_at=_iso(now - days * 86400), is_recurring=True, subscription_id="sub_rohan", fingerprint="fp_rohan")])
    r = e.apply_entities([PaymentAttempt(source="stripe", id="fail_rohan_now", customer_id=rohan, amount=2499, status="failed", decline_code="do_not_honor",
                                         decline_category="soft", raw_decline_code="do_not_honor", gateway="stripe", bank="SBI", attempted_at=_iso(now),
                                         is_recurring=True, subscription_id="sub_rohan", fingerprint="fp_rohan")])
    out["moat_case"] = r[0]["case_id"] if r else None

    # 4. Kavya: serial refunder. Refund pending + a retention save case where a discount is blocked
    kavya = cust("kavya", "Kavya Iyer", "kavya.iyer@example.in", "+919833333333")
    silent(e, [Subscription(source="razorpay", id="sub_kavya", customer_id=kavya, plan="pro", amount=1999, next_billing_at=_iso(now + 6 * 86400))])
    for i in range(6):
        oid = f"kav_ord_{i}"
        silent(e, [Order(id=oid, customer_id=kavya, items=[{"category": "apparel"}], amount=3499, created_at=_iso(now - (120 - i * 15) * 86400)),
                          Shipment(order_id=oid, carrier="Delhivery", delivered_at=_iso(now - (115 - i * 15) * 86400), pod=True),
                          PaymentAttempt(source="razorpay", id=f"kav_ok_{i}", customer_id=kavya, amount=3499, status="succeeded", gateway="razorpay",
                                         attempted_at=_iso(now - (120 - i * 15) * 86400))])
    e.hist(kavya)["offers_taken"] = 2
    for i in range(3):
        e.hist(kavya)["refunds"].append(Refund(id=f"kav_rf_{i}", customer_id=kavya, amount=3499, reason="not received", requested_at=_iso(now - (80 - i * 20) * 86400), status="processed"))
    for d in range(40, 20, -2):
        silent(e, [EngagementEvent(customer_id=kavya, type="usage", timestamp=_iso(now - d * 86400), value=5)])
    silent(e, [EngagementEvent(customer_id=kavya, type="downgrade", timestamp=_iso(now - 6 * 86400)),
                      Order(id="kav_ord_now", customer_id=kavya, items=[{"category": "apparel"}], amount=3499, created_at=_iso(now - 14 * 86400)),
                      Shipment(order_id="kav_ord_now", carrier="Delhivery", delivered_at=_iso(now - 9 * 86400), pod=True)])
    rr = e.apply_entities([Refund(id="kav_rf_now", customer_id=kavya, amount=3499, reason="not received", requested_at=_iso(now))])
    out["serial_refunder"] = rr[0]["case_id"] if rr else None

    # 5. Aman: strong-evidence dispute -> auto-submit
    aman = cust("aman", "Aman Verma", "aman.verma@example.in", "+919844444444", created_days=45)
    silent(e, [Order(id="aman_ord", customer_id=aman, items=[{"category": "electronics", "shipping": "express"}], amount=12499, created_at=_iso(now - 35 * 86400)),
                      Shipment(order_id="aman_ord", carrier="BlueDart", delivered_at=_iso(now - 30 * 86400), pod=True)])
    d = e.add_dispute(Dispute(id="DSP-2026-00142", customer_id=aman, network="Visa", amount=12499, opened_at=_iso(now), respond_by=_iso(now + 9 * 86400),
                              reason_code="Other Fraud - Card Absent Environment"),
                      {"delivered": True, "has_delivery_proof": True, "ip_geolocation_match": True, "avs_cvv_match": "both_match",
                       "has_3ds_authentication": True, "account_age_days": 45, "prior_orders": 3, "transaction_at": now - 35 * 86400})
    out["auto_dispute"] = d["case_id"]

    # 6. Neha: pre-dispute alert with weak evidence -> refund early beats fighting
    neha = cust("neha", "Neha Gupta", "neha.gupta@example.in", "+919855555555", created_days=20)
    d = e.add_dispute(Dispute(id="PRE-2026-0007", customer_id=neha, network="Mastercard", amount=900, opened_at=_iso(now), respond_by=_iso(now + 14 * 86400),
                              reason_code="Cardholder does not recognize", pre_dispute=True),
                      {"delivered": False, "has_delivery_proof": False, "ip_geolocation_match": False, "avs_cvv_match": "neither",
                       "has_3ds_authentication": False, "account_age_days": 20, "prior_orders": 1, "transaction_at": now - 12 * 86400})
    out["refund_vs_fight"] = d["case_id"]

    # 7. Vikram Traders: big-ticket dispute -> approval inbox (above the auto limit)
    vik = cust("vikram", "Vikram Traders", "accounts@vikramtraders.in", "+919866666666", created_days=400)
    d = e.add_dispute(Dispute(id="DSP-2026-00201", customer_id=vik, network="Visa", amount=48000, opened_at=_iso(now), respond_by=_iso(now + 2 * 86400),
                              reason_code="Merchandise not received"),
                      {"delivered": True, "has_delivery_proof": True, "ip_geolocation_match": True, "avs_cvv_match": "both_match",
                       "has_3ds_authentication": True, "account_age_days": 400, "prior_orders": 14, "transaction_at": now - 25 * 86400})
    out["approval_dispute"] = d["case_id"]

    # 8. COD orders: risky vs safe
    sur = cust("suresh", "Suresh Kumar", "suresh.k@example.in", "+919877777777", created_days=10, address="Room 5")
    ro = e.apply_entities([Order(id="cod_risky", customer_id=sur, items=[{"category": "electronics"}], amount=6499, payment_mode="COD", pincode="781001",
                                 address="Room 5", created_at=_iso(now - 5 * 3600))])
    safe = cust("lata", "Lata Menon", "lata.menon@example.in", "+919888888888", created_days=500)
    for i in range(4):
        silent(e, [Order(id=f"lata_o{i}", customer_id=safe, amount=1200, payment_mode="COD", pincode="560001", address="12, MG Road, near City Mall, Sector 4",
                                created_at=_iso(now - (100 - i * 20) * 86400), items=[{"category": "apparel"}]),
                          Shipment(order_id=f"lata_o{i}", delivered_at=_iso(now - (95 - i * 20) * 86400), pod=True)])
    rs = e.apply_entities([Order(id="cod_safe", customer_id=safe, items=[{"category": "apparel"}], amount=1499, payment_mode="COD", pincode="560001",
                                 address="12, MG Road, near City Mall, Sector 4", created_at=_iso(now - 2 * 3600))])
    out["rto_risky"], out["rto_safe"] = ro[0]["case_id"], rs[0]["case_id"]

    # 9. Divya: compound case (payment failure + refund request + unresolved ticket + downgrade)
    div = cust("divya", "Divya Nair", "divya.nair@example.in", "+919899999999")
    silent(e, [Subscription(source="razorpay", id="sub_divya", customer_id=div, plan="pro", amount=4999, next_billing_at=_iso(now + 4 * 86400)),
                      PaymentAttempt(source="razorpay", id="ok_divya", customer_id=div, amount=4999, status="succeeded", gateway="razorpay",
                                     attempted_at=_iso(now - 40 * 86400), is_recurring=True, subscription_id="sub_divya"),
                      Order(id="div_ord", customer_id=div, items=[{"category": "software", "digital": False}], amount=2999, created_at=_iso(now - 12 * 86400)),
                      Shipment(order_id="div_ord", delivered_at=_iso(now - 8 * 86400), pod=False)])
    for d_ in range(45, 20, -3):
        silent(e, [EngagementEvent(customer_id=div, type="usage", timestamp=_iso(now - d_ * 86400), value=6)])
    silent(e, [EngagementEvent(customer_id=div, type="ticket", timestamp=_iso(now - 6 * 86400)),
               EngagementEvent(customer_id=div, type="downgrade", timestamp=_iso(now - 4 * 86400))])
    e.apply_entities([Refund(id="div_rf", customer_id=div, amount=2999, reason="not as described", requested_at=_iso(now - 2 * 86400))])
    rd = e.apply_entities([PaymentAttempt(source="razorpay", id="fail_divya", customer_id=div, amount=4999, status="failed", decline_code="insufficient_funds",
                                          decline_category="soft", raw_decline_code="insufficient_funds", gateway="razorpay", bank="HDFC", attempted_at=_iso(now),
                                          is_recurring=True, subscription_id="sub_divya")])
    out["compound"] = div
    return out


def seed_demo(seed: int = 7, customers: int = 240, days: int = 56) -> tuple[ImpulseEngine, dict]:
    e = ImpulseEngine(seed=seed)
    b = DemoBuilder(e, seed)
    start = e.now() - days * 86400
    e.set_clock(start)
    b.make_customers(customers, start)
    e.set_clock(None)
    b.history_days(days)
    scenarios = scripted_scenarios(e)
    e.audit("system", "demo_seeded", {"customers": len(e.history), "cases": len(e.cases), "ledger_entries": len(e.ledger.entries)})
    return e, scenarios


def refill_samples(e: ImpulseEngine, count: int = 4) -> int:
    """Add fresh decisions that need a human, so the Approval Inbox is never empty in a demo."""
    import uuid
    rng = random.Random(uuid.uuid4().int % 10**9)
    now = e.now()
    before = sum(1 for a in e.approvals.values() if a["status"] == "pending")
    kinds = ["big_dispute", "refund", "compound", "pre_dispute", "big_dispute"]
    for i in range(count):
        kind = kinds[i % len(kinds)]
        tag = uuid.uuid4().hex[:6]
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        cid = f"razorpay:s_{tag}"
        e.apply_entities([Customer(source="razorpay", id=cid, name=name, email=f"{name.lower().replace(' ', '.')}.{tag}@example.in",
                                   phone=f"+9198{rng.randint(10000000, 99999999)}", source_ids={"razorpay": f"s_{tag}"},
                                   created_at=_iso(now - rng.randint(60, 500) * 86400), address=rng.choice(ADDR))])
        root = e.resolver.canonical(cid)
        if kind in ("big_dispute", "pre_dispute"):
            big = kind == "big_dispute"
            amt = rng.randint(30000, 95000) if big else rng.randint(700, 2400)
            strong = big or rng.random() < 0.3
            oid = f"ord_{tag}"
            silent(e, [Order(id=oid, customer_id=root, items=[{"category": rng.choice(["electronics", "software", "apparel"]), "shipping": "express"}], amount=amt, created_at=_iso(now - 20 * 86400)),
                       Shipment(order_id=oid, carrier="Delhivery", delivered_at=_iso(now - 15 * 86400), pod=strong)])
            d = Dispute(id=f"{'DSP' if big else 'PRE'}-{tag.upper()}", customer_id=root, network=rng.choice(["Visa", "Mastercard"]), amount=amt, opened_at=_iso(now),
                        respond_by=_iso(now + rng.randint(2, 12) * 86400), reason_code=rng.choice(["Merchandise not received", "Fraud", "Not as described"]), pre_dispute=not big)
            e.add_dispute(d, {"delivered": True, "has_delivery_proof": strong, "ip_geolocation_match": strong, "avs_cvv_match": "both_match" if strong else "neither",
                              "has_3ds_authentication": strong, "account_age_days": rng.randint(40, 600), "prior_orders": rng.randint(1, 12), "transaction_at": now - 20 * 86400})
        elif kind == "refund":
            amt = rng.choice([2499, 3499, 4999])
            for k in range(6):
                oid = f"o_{tag}_{k}"
                silent(e, [Order(id=oid, customer_id=root, items=[{"category": "apparel"}], amount=amt, created_at=_iso(now - (150 - k * 20) * 86400)),
                           Shipment(order_id=oid, carrier="BlueDart", delivered_at=_iso(now - (145 - k * 20) * 86400), pod=True),
                           PaymentAttempt(source="razorpay", id=f"ok_{tag}_{k}", customer_id=root, amount=amt, status="succeeded", gateway="razorpay", attempted_at=_iso(now - (150 - k * 20) * 86400))])
            for k in range(3):
                e.hist(root)["refunds"].append(Refund(id=f"rf_{tag}_{k}", customer_id=root, amount=amt, reason="not received", requested_at=_iso(now - (90 - k * 20) * 86400), status="processed"))
            e.apply_entities([Refund(id=f"rf_{tag}_now", customer_id=root, amount=amt, reason="not received", requested_at=_iso(now))])
        else:  # compound: several problems on one subscriber
            sid = f"sub_{tag}"
            silent(e, [Subscription(source="razorpay", id=sid, customer_id=root, plan="pro", amount=rng.choice([2999, 4999]), next_billing_at=_iso(now + 5 * 86400)),
                       PaymentAttempt(source="razorpay", id=f"ok_{tag}", customer_id=root, amount=2999, status="succeeded", gateway="razorpay", attempted_at=_iso(now - 40 * 86400), is_recurring=True, subscription_id=sid)])
            for d_ in range(45, 20, -3):
                silent(e, [EngagementEvent(customer_id=root, type="usage", timestamp=_iso(now - d_ * 86400), value=6)])
            silent(e, [EngagementEvent(customer_id=root, type="ticket", timestamp=_iso(now - 5 * 86400)), EngagementEvent(customer_id=root, type="downgrade", timestamp=_iso(now - 3 * 86400))])
            e.apply_entities([Refund(id=f"rf_{tag}", customer_id=root, amount=1999, reason="not as described", requested_at=_iso(now - 86400))])
            e.apply_entities([PaymentAttempt(source="razorpay", id=f"fail_{tag}", customer_id=root, amount=2999, status="failed", decline_code="insufficient_funds", decline_category="soft",
                                             raw_decline_code="insufficient_funds", gateway="razorpay", bank="HDFC", attempted_at=_iso(now), is_recurring=True, subscription_id=sid)])
    return sum(1 for a in e.approvals.values() if a["status"] == "pending") - before


def try_payment(e: ImpulseEngine, reason: str, amount: float, recurring: bool = True, prior_failures: int = 0) -> dict:
    """Playground: fail one payment for a fresh sample customer and let Impulse decide."""
    import uuid
    from .declines import normalize_decline
    rng = random.Random(uuid.uuid4().int % 10**9)
    now = e.now()
    tag = uuid.uuid4().hex[:6]
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    cid = f"razorpay:t_{tag}"
    e.apply_entities([Customer(source="razorpay", id=cid, name=name, email=f"{name.lower().replace(' ', '.')}.{tag}@example.in", phone=f"+9198{rng.randint(10000000, 99999999)}",
                               source_ids={"razorpay": f"t_{tag}"}, created_at=_iso(now - 200 * 86400))])
    root = e.resolver.canonical(cid)
    sid = f"sub_{tag}" if recurring else None
    if recurring:
        silent(e, [Subscription(source="razorpay", id=sid, customer_id=root, plan="pro", amount=amount, next_billing_at=_iso(now + 5 * 86400))])
    silent(e, [PaymentAttempt(source="razorpay", id=f"ok_{tag}", customer_id=root, amount=amount, status="succeeded", gateway="razorpay", attempted_at=_iso(now - 45 * 86400),
                              is_recurring=recurring, subscription_id=sid)])
    code, cat = normalize_decline("razorpay", reason)
    for k in range(prior_failures):
        silent(e, [PaymentAttempt(source="razorpay", id=f"pf_{tag}_{k}", customer_id=root, amount=amount, status="failed", decline_code=code, decline_category=cat, raw_decline_code=reason,
                                  gateway="razorpay", attempted_at=_iso(now - (12 * (prior_failures - k)) * 86400), is_recurring=recurring, subscription_id=sid)])
        for d_ in (40, 30, 20):
            pass
    if prior_failures:
        for d_ in range(50, 20, -4):
            silent(e, [EngagementEvent(customer_id=root, type="usage", timestamp=_iso(now - d_ * 86400), value=6)])
    recs = e.apply_entities([PaymentAttempt(source="razorpay", id=f"try_{tag}", customer_id=root, amount=amount, status="failed", decline_code=code, decline_category=cat,
                                            raw_decline_code=reason, gateway="razorpay", bank="HDFC", attempted_at=_iso(now), is_recurring=recurring, subscription_id=sid)])
    return next(r for r in recs if r["module"] == "payments")
