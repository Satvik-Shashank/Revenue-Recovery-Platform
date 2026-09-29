"""Language layer. Claude (when ANTHROPIC_API_KEY is set) drafts prose; decisions stay deterministic.

Three uses: evidence narrative for a dispute, customer message inside an APPROVED template, and
'ask the ledger' questions. Every function works without an API key using deterministic templates."""

import os
import re

MODEL = os.getenv("IMPULSE_LLM_MODEL", "claude-sonnet-5-5")


def llm_available() -> bool:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def _complete(system: str, user: str, max_tokens: int = 500) -> str | None:
    if not llm_available():
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                     messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip() or None
    except Exception:
        return None


def evidence_narrative(dispute: dict, analysis: dict, pack: dict) -> dict:
    """Prose summary of the representment case. Facts come only from the pack; the model may not add any."""
    present = [i["label"] for i in pack["items"] if i["present"] and i["role"] != "not_required"]
    missing = [i["label"] for i in pack["items"] if not i["present"] and i["role"] == "compelling"]
    rc = analysis.get("classification", {}).get("predicted_reason_code")
    fallback = (f"Dispute {dispute.get('dispute_id')} (₹{dispute.get('dispute_amount', 0):,.0f}, reason code {rc}). "
                f"The merchant holds: {', '.join(present) if present else 'no compelling evidence'}. "
                + (f"Not available: {', '.join(missing)}. " if missing else "")
                + f"Evidence completeness is {pack['completeness']:.0%}.")
    text = _complete("You write concise, factual chargeback representment summaries. Use ONLY the facts provided; "
                     "never invent evidence, dates or amounts. 90 words max.",
                     f"Dispute: {dispute}\nReason code: {rc}\nEvidence present: {present}\nMissing: {missing}")
    return {"text": text or fallback, "source": "claude" if text else "template"}


def customer_message(action: str, rendered: dict | None) -> dict:
    """Polish an approved template's tone. The template facts/links are passed through verbatim."""
    if not rendered:
        return {"text": None, "source": "none"}
    text = _complete("Rewrite this customer message to be warm and brief. Keep every number and link EXACTLY as written. 45 words max.",
                     rendered["body"], 200)
    if text and all(tok in text for tok in re.findall(r"https?://\S+|₹[\d,]+", rendered["body"])):
        return {"text": text, "source": "claude"}
    return {"text": rendered["body"], "source": "template"}


def answer_question(question: str, ledger, engine) -> dict:
    """Answer from the ledger; deterministic intents first, LLM only phrases what the numbers already say."""
    q = question.lower()
    s = ledger.summary()
    mods = s["by_module"]
    facts = {"summary": s}
    HELP = [
        (("start", "onboard", "begin", "get started", "how do i", "how to use", "setup", "set up"),
         "Getting started: 1) Run the free Leak Audit on a spreadsheet export. 2) Connect Razorpay or Stripe webhooks. 3) Begin in recommend-only mode and review suggestions. 4) Let low-risk actions run on their own once you trust them. The full walkthrough is on the Getting started page."),
        (("data", "upload", "csv", "file", "synthetic", "sample", "fake", "real"),
         "Right now the workspace uses made-up sample data. Files you upload to the Leak Audit are analysed in memory for the report and are not added to the workspace or stored. Connecting a gateway is how real events would flow in."),
        (("connect", "webhook", "razorpay", "stripe", "gateway", "integration"),
         "Impulse connects to Razorpay and Stripe through webhooks, plus CSV/Excel upload and a REST API for custom events. Other gateways and billing tools are on the roadmap. Set the webhook secret on the Connections page."),
        (("approve", "approval", "control", "automat", "autonomy"),
         "You choose per module and per action whether Impulse acts on its own, asks for approval first, or only recommends. Anything above your auto-approve limit always waits for a person. Change this in Settings."),
        (("safe", "guardrail", "security", "card number", "privacy"),
         "Guardrails include: never retry a permanent decline, cap how often a customer is contacted, and tie discounts to customer value. Card numbers are never stored, only gateway tokens."),
        (("price", "pricing", "cost", "charge", "billing model"),
         "You pay a share of the money Impulse recovers beyond what you would have recovered on your own, measured against a control group. No extra recovery means no fee."),
        (("pillar", "what do you do", "what is impulse", "what does impulse", "services", "modules"),
         "Impulse tackles four leaks: failed payments (Payment Recovery), money taken back (Clawback Defense), customers quietly stopping (Retention Rescue), and revenue never billed or collected (Billing & Collections)."),
    ]
    for keys, text in HELP:
        if any(k in q for k in keys):
            return {"answer": text, "source": "guide", "facts": {}}
    if any(w in q for w in ("fee", "invoice", "pay you", "owe")):
        a = (f"Impulse's performance fee is ₹{s['impulse_fee']:,.0f} ({s['fee_pct']:.0f}% of ₹{s['net_incremental']:,.0f} net incremental recovery). "
             f"Your net gain after the fee is ₹{s['merchant_net_gain']:,.0f}.")
    elif any(w in q for w in ("best", "top", "most")) and mods:
        best = max(mods.items(), key=lambda kv: kv[1]["net"])
        a = f"{best[0].title()} is the top performer: ₹{best[1]['net']:,.0f} net incremental across {best[1]['cases']} cases."
    elif "holdout" in q or "baseline" in q or "prove" in q:
        m = mods.get("payments")
        a = (f"Payments baseline is {m['baseline_rate']:.0%} ({m['baseline_basis']}) vs {m['treatment_rate']:.0%} with Impulse, "
             f"measured on {m['holdout_cases']} holdout cases." if m else "No payment cases recorded yet.")
    elif "chargeback" in q or "dispute" in q:
        m = mods.get("clawback")
        a = (f"Clawback Defense: ₹{m['gross_recovered']:,.0f} retained over {m['cases']} decided cases, ₹{m['net']:,.0f} net after costs." if m
             else "No disputes decided yet.")
    elif any(w in q for w in ("recover", "how much", "total", "made")):
        a = (f"Gross recovered ₹{s['gross_recovered']:,.0f}; net incremental (beyond your baseline, after costs) ₹{s['net_incremental']:,.0f}; "
             f"audited by {s['entries']} hash-chained ledger entries.")
    else:
        a = ("I can explain how to get started, what data is being used, how to connect Razorpay or Stripe, what needs your approval, "
             "pricing, or answer questions about results. Try: 'how do I get started?'")
    phrased = _complete("Rephrase this answer in one or two clear sentences. Keep all numbers exactly.", a, 150)
    return {"answer": phrased or a, "source": "claude" if phrased else "ledger", "facts": facts["summary"]["by_module"]}
