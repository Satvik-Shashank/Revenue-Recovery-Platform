"""Decline-code normalization: every gateway names failures differently; map to one taxonomy."""

TAXONOMY = [
    "insufficient_funds", "expired_card", "do_not_honor", "suspected_fraud", "auth_required",
    "lost_stolen", "invalid_card", "bank_downtime", "limit_exceeded", "other",
]

CATEGORY = {
    "insufficient_funds": "soft", "limit_exceeded": "soft", "do_not_honor": "soft", "other": "soft",
    "bank_downtime": "bank",
    "auth_required": "auth",
    "expired_card": "hard", "suspected_fraud": "hard", "lost_stolen": "hard", "invalid_card": "hard",
}

STRIPE = {
    "insufficient_funds": "insufficient_funds", "expired_card": "expired_card", "do_not_honor": "do_not_honor",
    "generic_decline": "do_not_honor", "fraudulent": "suspected_fraud", "merchant_blacklist": "suspected_fraud",
    "authentication_required": "auth_required", "authentication_not_handled": "auth_required",
    "lost_card": "lost_stolen", "stolen_card": "lost_stolen", "pickup_card": "lost_stolen",
    "incorrect_number": "invalid_card", "invalid_number": "invalid_card", "invalid_cvc": "invalid_card",
    "incorrect_cvc": "invalid_card", "card_not_supported": "invalid_card",
    "issuer_not_available": "bank_downtime", "processing_error": "bank_downtime", "try_again_later": "bank_downtime",
    "card_velocity_exceeded": "limit_exceeded", "withdrawal_count_limit_exceeded": "limit_exceeded",
    "amount_too_large": "limit_exceeded",
}

RAZORPAY = {
    "insufficient_funds": "insufficient_funds", "card_expired": "expired_card", "expired_card": "expired_card",
    "payment_declined": "do_not_honor", "issuer_declined": "do_not_honor", "do_not_honor": "do_not_honor",
    "fraud_suspected": "suspected_fraud", "risk_check_failed": "suspected_fraud",
    "authentication_failed": "auth_required", "3ds_failed": "auth_required", "otp_failed": "auth_required",
    "card_lost": "lost_stolen", "card_stolen": "lost_stolen",
    "invalid_card_number": "invalid_card", "invalid_cvv": "invalid_card", "card_not_enabled": "invalid_card",
    "bank_unavailable": "bank_downtime", "gateway_timeout": "bank_downtime", "issuer_down": "bank_downtime",
    "transaction_limit_exceeded": "limit_exceeded", "limit_exceeded": "limit_exceeded",
}

PAYU = {
    "insufficient funds": "insufficient_funds", "card expired": "expired_card", "do not honour": "do_not_honor",
    "bank down": "bank_downtime", "invalid card": "invalid_card", "auth failed": "auth_required",
}

_TABLES = {"stripe": STRIPE, "razorpay": RAZORPAY, "payu": PAYU}
_KEYWORDS = [
    ("insufficient", "insufficient_funds"), ("expire", "expired_card"), ("fraud", "suspected_fraud"),
    ("stolen", "lost_stolen"), ("lost", "lost_stolen"), ("auth", "auth_required"), ("otp", "auth_required"),
    ("3ds", "auth_required"), ("limit", "limit_exceeded"), ("invalid", "invalid_card"),
    ("timeout", "bank_downtime"), ("unavailable", "bank_downtime"), ("down", "bank_downtime"),
    ("honor", "do_not_honor"), ("honour", "do_not_honor"), ("declin", "do_not_honor"),
]


def normalize_decline(source: str, raw: str | None) -> tuple[str, str]:
    """Return (decline_code, decline_category) for a gateway-specific raw code."""
    if not raw:
        return "other", CATEGORY["other"]
    key = str(raw).strip().lower()
    table = _TABLES.get(source.lower(), {})
    code = table.get(key)
    if code is None:
        code = next((v for k, v in _KEYWORDS if k in key), "other")
    return code, CATEGORY[code]
