"""Action layer: idempotent, logged, reversible-where-possible execution tied to a case.

Delivery is SIMULATED (no real email/SMS/WhatsApp is sent); each record shows exactly what would go out."""

import time
import uuid

TEMPLATES = {
    "payment_update_link": {"approved": True, "subject": "Update your payment method",
                            "body": "Hi {name}, your payment of ₹{amount:,.0f} didn't go through. Update your method in one tap (UPI supported): {link}"},
    "upi_fallback": {"approved": True, "subject": "Pay via UPI instead",
                     "body": "Hi {name}, we couldn't charge your card. You can complete the ₹{amount:,.0f} payment via UPI here: {link}"},
    "pre_debit_notice": {"approved": True, "subject": "Upcoming payment",
                         "body": "Hi {name}, we will attempt to charge ₹{amount:,.0f} on {when}. Manage your plan: {link}"},
    "offer_pause": {"approved": True, "subject": "Need a break?",
                    "body": "Hi {name}, before your subscription lapses you can pause it instead: {link}"},
    "offer_downgrade": {"approved": True, "subject": "A lighter plan",
                        "body": "Hi {name}, switch to a lighter plan and keep your data: {link}"},
    "discount": {"approved": True, "subject": "We'd like to keep you",
                 "body": "Hi {name}, enjoy {discount_pct:.0f}% off for {months} months if you stay: {link}"},
    "win_back_offer": {"approved": True, "subject": "Come back", "body": "Hi {name}, we saved a special offer for you: {link}"},
    "otp_verify": {"approved": True, "subject": "Confirm your order", "body": "Enter the OTP sent to you to confirm your COD order: {link}"},
    "prepaid_nudge": {"approved": True, "subject": "Pay now and save",
                      "body": "Hi {name}, pay online now and save ₹{incentive_inr:,.0f} on your order: {link}"},
    "request_proof": {"approved": True, "subject": "Help us with your refund request",
                      "body": "Hi {name}, to process your refund please share a photo or details of the issue: {link}"},
    "offer_replacement_credit": {"approved": True, "subject": "Replacement or credit",
                                 "body": "Hi {name}, we can send a replacement or issue store credit of ₹{credit:,.0f}: {link}"},
}

REVERSIBLE = {"schedule_retry", "payment_update_link", "upi_fallback", "offer_pause", "offer_downgrade", "discount",
              "hold_order", "otp_verify", "prepaid_nudge", "request_proof"}


class ActionLayer:
    def __init__(self):
        self.records: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}

    def render(self, action: str, ctx: dict) -> dict | None:
        tpl = TEMPLATES.get(action)
        if not tpl or not tpl["approved"]:
            return None
        try:
            return {"subject": tpl["subject"], "body": tpl["body"].format(**ctx)}
        except (KeyError, IndexError, ValueError):
            return {"subject": tpl["subject"], "body": tpl["body"]}

    def execute(self, case, decision, status: str = "executed", template_ctx: dict | None = None) -> dict:
        """Idempotent on case+action: re-executing returns the existing record."""
        ch = decision.chosen
        if not ch:
            raise ValueError("decision has no chosen action")
        key = f"{case.id}:{ch['action']}"
        if key in self.by_key:
            return self.records[self.by_key[key]]
        ctx = {"name": case.features.get("customer_name", "there"), "amount": case.amount,
               "link": f"https://impulse.pay/{uuid.uuid4().hex[:8]}", "when": (ch.get("params") or {}).get("retry_at", "soon"),
               **(ch.get("params") or {}), **(template_ctx or {})}
        rec = {"id": f"act_{uuid.uuid4().hex[:8]}", "case_id": case.id, "decision_id": decision.id, "customer_id": case.customer_id,
               "module": case.module, "action": ch["action"], "category": ch.get("category"), "channel": ch.get("channel"),
               "params": ch.get("params") or {}, "status": status, "idempotency_key": key, "at": time.time(),
               "reversible": ch["action"] in REVERSIBLE, "message": self.render(ch["action"], ctx) if ch.get("channel") else None,
               "delivery": "simulated" if ch.get("channel") else None}
        self.records[rec["id"]] = rec
        self.by_key[key] = rec["id"]
        return rec

    def set_status(self, action_id: str, status: str) -> dict:
        self.records[action_id]["status"] = status
        return self.records[action_id]

    def undo(self, action_id: str) -> dict:
        rec = self.records[action_id]
        if not rec["reversible"]:
            raise ValueError(f"{rec['action']} cannot be reversed")
        rec["status"] = "reversed"
        return rec
