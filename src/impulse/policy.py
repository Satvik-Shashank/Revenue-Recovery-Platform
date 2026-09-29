"""Merchant policy-as-config: autonomy levels, budgets, guardrails and economics in one editable dict."""

import copy

AUTONOMY_LEVELS = ("auto", "approve", "recommend")

DEFAULT_POLICY = {
    "version": 1,
    # default autonomy per module; action_overrides win over module defaults
    "autonomy": {"payments": "auto", "clawback": "approve", "retention": "approve",
                 "refunds": "approve", "rto": "auto", "billing": "recommend"},
    "action_overrides": {"schedule_retry": "auto", "payment_update_link": "auto", "submit_evidence": "auto",
                         "discount": "approve", "block_order": "approve", "accept_liability": "approve",
                         "decline_refund": "approve", "partial_refund": "approve", "approve_refund": "auto",
                         "request_proof": "auto", "offer_replacement_credit": "approve", "refund_early": "approve",
                         "otp_verify": "auto", "prepaid_nudge": "auto", "call_verify": "auto",
                         "offer_pause": "auto", "offer_downgrade": "approve", "upi_fallback": "auto",
                         "ship_as_is": "auto"},
    "approval_threshold_inr": 25000,       # anything above always needs a human
    "contact_cap_per_7d": 3,
    "max_retries_per_payment": 4,
    "discount_ceiling_pct_of_ltv": 0.08,    # a discount may cost at most 8% of customer LTV
    "budgets_inr_per_month": {"offers": 50000, "prepaid_incentive": 20000},
    "holdout_pct": 10,                      # % of failed payments left on the merchant's original logic
    "fee_pct": 12.0,                        # performance fee on net incremental recovery
    "platform_fee_inr_per_month": 0,
    # economic assumptions (modelling assumptions, not cited industry data)
    "dispute_fee_inr": 300,                 # network/gateway fee per lost dispute
    "ratio_penalty_inr": 150,               # chargeback-ratio damage per dispute
    "evidence_cost_inr": 120,               # analyst/ops cost to fight one dispute
    "retry_cost_inr": 2,
    "message_cost_inr": {"email": 0.2, "sms": 0.8, "whatsapp": 0.9, "in_app": 0.05},
    "guardrails": {"no_retry_hard_decline": True, "contact_cap": True, "discount_ceiling": True,
                   "no_reward_serial_abusers": True, "offer_budget": True, "recurring_compliance": True,
                   "retry_cap": True, "opt_out": True},
}


class Policy:
    def __init__(self, overrides: dict | None = None):
        self.data = copy.deepcopy(DEFAULT_POLICY)
        if overrides:
            self.update(overrides)

    def update(self, patch: dict) -> dict:
        def merge(dst, src):
            for k, v in src.items():
                if k not in dst:
                    raise ValueError(f"unknown policy key: {k}")
                if isinstance(dst[k], dict) and isinstance(v, dict):
                    merge(dst[k], v)
                else:
                    dst[k] = v
        candidate = copy.deepcopy(self.data)
        merge(candidate, patch or {})
        for scope in ("autonomy", "action_overrides"):
            for k, v in candidate[scope].items():
                if v not in AUTONOMY_LEVELS:
                    raise ValueError(f"{scope}.{k} must be one of {AUTONOMY_LEVELS}")
        if not 0 <= candidate["holdout_pct"] <= 50:
            raise ValueError("holdout_pct must be between 0 and 50")
        if not 0 <= candidate["fee_pct"] <= 50:
            raise ValueError("fee_pct must be between 0 and 50")
        candidate["version"] = self.data["version"] + 1
        self.data = candidate
        return self.data

    def __getitem__(self, key):
        return self.data[key]

    def autonomy_for(self, module: str, action: str) -> str:
        return self.data["action_overrides"].get(action) or self.data["autonomy"].get(module, "approve")
