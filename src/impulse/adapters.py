"""Per-source adapters: raw gateway payload -> canonical entities. Raise MappingError on bad input."""

from datetime import datetime, timezone
from .declines import normalize_decline
from .schema import (Customer, Dispute, EngagementEvent, Invoice, Order, PaymentAttempt, PaymentMethod,
                     Refund, Shipment, Subscription)


class MappingError(ValueError):
    pass


def _iso(ts) -> str:
    if ts is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
    return str(ts)


def _need(d: dict, *path):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            raise MappingError(f"missing field: {'.'.join(path)}")
        cur = cur[p]
    return cur


def _prov(source: str, key) -> str:
    return f"{source}:{key}"


# ── Razorpay (amounts in paise) ───────────────────────────────────────────────

def razorpay_adapter(event: dict) -> list:
    name = _need(event, "event")
    payload = _need(event, "payload")
    created = event.get("created_at")
    out = []
    if name.startswith("payment.dispute"):
        d = _need(payload, "dispute", "entity")
        cust = _prov("razorpay", d.get("customer_id") or d.get("contact") or _need(d, "payment_id"))
        out.append(Dispute(
            source="razorpay", source_id=d["id"], id=d["id"], customer_id=cust, payment_id=d.get("payment_id"),
            reason_code=d.get("reason_code"), network=d.get("network"), amount=_need(d, "amount") / 100,
            opened_at=_iso(d.get("created_at", created)),
            respond_by=_iso(d["respond_by"]) if d.get("respond_by") else None,
            status="open", pre_dispute=name.endswith("pre_created") or bool(d.get("pre_dispute"))))
        return out
    if name.startswith("refund."):
        r = _need(payload, "refund", "entity")
        cust = _prov("razorpay", r.get("customer_id") or _need(r, "payment_id"))
        out.append(Refund(source="razorpay", source_id=r["id"], id=r["id"], customer_id=cust,
                          payment_id=r.get("payment_id"), amount=_need(r, "amount") / 100,
                          reason=(r.get("notes") or {}).get("reason"), requested_at=_iso(r.get("created_at", created))))
        return out
    if name.startswith("subscription."):
        s = _need(payload, "subscription", "entity")
        cust = _prov("razorpay", s.get("customer_id") or s["id"])
        status = {"halted": "past_due", "cancelled": "canceled", "paused": "paused"}.get(s.get("status"), "active")
        out.append(Subscription(source="razorpay", source_id=s["id"], id=s["id"], customer_id=cust,
                                plan=s.get("plan_id", "standard"), amount=s.get("amount", 0) / 100, status=status,
                                next_billing_at=_iso(s["charge_at"]) if s.get("charge_at") else None,
                                seats=s.get("quantity", 1)))
        return out
    if name.startswith("payment."):
        p = _need(payload, "payment", "entity")
        key = p.get("customer_id") or p.get("email") or p["id"]
        cust = _prov("razorpay", key)
        card = p.get("card") or {}
        out.append(Customer(source="razorpay", id=cust, email=p.get("email"), phone=p.get("contact"),
                            source_ids={"razorpay": key}, created_at=_iso(created)))
        method = p.get("method", "card")
        fp = card.get("fingerprint")  # last4+network is NOT unique, so never used as an identity key
        expiry = None
        if card.get("expiry_year"):
            expiry = f"{card['expiry_year']}-{int(card['expiry_month']):02d}"
        out.append(PaymentMethod(source="razorpay", customer_id=cust,
                                 type=method if method in ("card", "upi", "netbanking", "wallet") else "card",
                                 network=card.get("network"), bank=p.get("bank") or card.get("issuer"),
                                 fingerprint=fp, expiry=expiry))
        failed = name == "payment.failed" or p.get("status") == "failed"
        raw = p.get("error_reason") or p.get("error_code") or p.get("error_description")
        code, cat = normalize_decline("razorpay", raw) if failed else (None, None)
        out.append(PaymentAttempt(
            source="razorpay", source_id=p["id"], id=p["id"], customer_id=cust, amount=_need(p, "amount") / 100,
            currency=p.get("currency", "INR"), status="failed" if failed else "succeeded",
            decline_code=code, decline_category=cat, raw_decline_code=raw if failed else None, gateway="razorpay",
            method_type=method, bank=p.get("bank") or card.get("issuer"),
            attempted_at=_iso(p.get("created_at", created)),
            is_recurring=bool(p.get("subscription_id") or p.get("invoice_id")),
            subscription_id=p.get("subscription_id"), fingerprint=fp))
        return out
    raise MappingError(f"unsupported razorpay event: {name}")


# ── Stripe (amounts in minor units) ────────────────────────────────────────

def stripe_adapter(event: dict) -> list:
    typ = _need(event, "type")
    obj = _need(event, "data", "object")
    created = event.get("created")
    out = []
    cust_key = obj.get("customer") or obj.get("receipt_email") or _need(obj, "id")
    cust = _prov("stripe", cust_key)
    meta = obj.get("metadata") or {}
    if typ.startswith("charge.dispute") or typ.startswith("radar.early_fraud_warning"):
        due = (obj.get("evidence_details") or {}).get("due_by")
        out.append(Dispute(source="stripe", source_id=obj["id"], id=obj["id"], customer_id=cust,
                           payment_id=obj.get("payment_intent") or obj.get("charge"),
                           reason_code=obj.get("reason"), network=(obj.get("network") or "").title() or None,
                           amount=_need(obj, "amount") / 100, opened_at=_iso(obj.get("created", created)),
                           respond_by=_iso(due) if due else None, pre_dispute=typ.startswith("radar")))
        return out
    if typ == "charge.refunded" or typ.startswith("refund."):
        out.append(Refund(source="stripe", source_id=obj["id"], id=obj["id"], customer_id=cust,
                          payment_id=obj.get("payment_intent"),
                          amount=obj.get("amount_refunded", obj.get("amount", 0)) / 100,
                          reason=obj.get("reason"), requested_at=_iso(obj.get("created", created))))
        return out
    if typ.startswith("customer.subscription"):
        status = {"past_due": "past_due", "canceled": "canceled", "paused": "paused",
                  "unpaid": "past_due"}.get(obj.get("status"), "active")
        item = ((obj.get("items") or {}).get("data") or [{}])[0]
        price = item.get("price") or {}
        out.append(Subscription(source="stripe", source_id=obj["id"], id=obj["id"], customer_id=cust,
                                plan=price.get("nickname") or price.get("id", "standard"),
                                amount=(price.get("unit_amount") or 0) / 100, status=status,
                                next_billing_at=_iso(obj["current_period_end"]) if obj.get("current_period_end") else None,
                                seats=item.get("quantity", 1)))
        return out
    if typ.startswith("invoice.") and typ != "invoice.payment_failed":
        out.append(Invoice(source="stripe", source_id=obj["id"], id=obj["id"], customer_id=cust,
                           amount=obj.get("amount_due", 0) / 100,
                           due_date=_iso(obj.get("due_date") or obj.get("created", created)),
                           paid_at=_iso((obj.get("status_transitions") or {}).get("paid_at")) if obj.get("paid") else None,
                           status="paid" if obj.get("paid") else "open"))
        return out
    if typ.startswith("payment_intent") or typ == "invoice.payment_failed":
        err = obj.get("last_payment_error") or {}
        pm = err.get("payment_method") or obj.get("payment_method_details") or {}
        card = pm.get("card") or {}
        out.append(Customer(source="stripe", id=cust, email=obj.get("receipt_email") or meta.get("email"),
                            phone=meta.get("phone"), source_ids={"stripe": cust_key}, created_at=_iso(created)))
        expiry = f"{card['exp_year']}-{int(card['exp_month']):02d}" if card.get("exp_year") else None
        out.append(PaymentMethod(source="stripe", customer_id=cust, type="card", network=card.get("brand"),
                                 bank=meta.get("bank"), fingerprint=card.get("fingerprint"), expiry=expiry))
        failed = typ.endswith("payment_failed")
        raw = err.get("decline_code") or err.get("code")
        code, cat = normalize_decline("stripe", raw) if failed else (None, None)
        out.append(PaymentAttempt(
            source="stripe", source_id=obj["id"], id=obj["id"], customer_id=cust,
            amount=(obj.get("amount") or obj.get("amount_due") or 0) / 100,
            currency=(obj.get("currency") or "inr").upper(),
            status="failed" if failed else "succeeded", decline_code=code, decline_category=cat,
            raw_decline_code=raw if failed else None, gateway="stripe", method_type="card",
            bank=meta.get("bank"), attempted_at=_iso(obj.get("created", created)),
            is_recurring=bool(obj.get("invoice") or meta.get("recurring") or typ.startswith("invoice")),
            subscription_id=obj.get("subscription") or meta.get("subscription_id"),
            fingerprint=card.get("fingerprint")))
        return out
    raise MappingError(f"unsupported stripe event: {typ}")


def generic_adapter(event: dict) -> list:
    """Custom events pushed via the public API: {"entity": "engagement", ...canonical fields}."""
    kind = _need(event, "entity")
    body = {k: v for k, v in event.items() if k not in ("entity", "event_id")}
    model = {"engagement": EngagementEvent, "customer": Customer, "subscription": Subscription,
             "invoice": Invoice, "payment_attempt": PaymentAttempt, "refund": Refund, "dispute": Dispute,
             "order": Order, "shipment": Shipment, "payment_method": PaymentMethod}.get(kind)
    if model is None:
        raise MappingError(f"unknown entity: {kind}")
    try:
        return [model(**body)]
    except Exception as exc:  # pydantic validation
        raise MappingError(str(exc)) from exc


ADAPTERS = {"razorpay": razorpay_adapter, "stripe": stripe_adapter, "custom": generic_adapter}
