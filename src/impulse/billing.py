"""Billing Assurance & Collections (missed money): revenue-assurance checks, lateness prediction,
prioritised collections worklist and promise-to-pay tracking. Tier-3 mini-demo on planted-error data.

VERIFY before citing: MSME payment-delay rules (Section 43B(h) and the 45-day norm)."""

import random
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

MSME_DAYS = 45  # verify before citing

DAY = 86400


def _d(v) -> datetime:
    return datetime.fromisoformat(v).replace(tzinfo=timezone.utc) if isinstance(v, str) else v


# ── A. revenue assurance ─────────────────────────────────────────────────────

def run_assurance(contracts, invoices, usage, seats, credits, payments, today: datetime) -> list[dict]:
    """Each input is a list of dicts. Returns findings, each with the ₹ at stake and a suggested fix."""
    f = []
    inv_by_contract = defaultdict(list)
    for inv in invoices:
        inv_by_contract[inv["contract_id"]].append(inv)

    for c in contracts:
        invs = inv_by_contract.get(c["id"], [])
        # 1. renewals never invoiced / wrong price
        due_cycles = c.get("cycles_due", 1)
        if len(invs) < due_cycles:
            missing = due_cycles - len(invs)
            f.append({"check": "contract_vs_invoice", "severity": "high", "customer": c["customer"], "contract": c["id"],
                      "amount": round(missing * c["price"], 2),
                      "detail": f"{missing} renewal cycle(s) never invoiced at ₹{c['price']:,.0f}",
                      "fix": "Generate the missing invoice(s)"})
        for inv in invs:
            if abs(inv["amount"] - c["price"]) > 0.01 * c["price"] and not inv.get("discount_applied"):
                f.append({"check": "contract_vs_invoice", "severity": "medium", "customer": c["customer"], "contract": c["id"],
                          "amount": round(c["price"] - inv["amount"], 2),
                          "detail": f"invoice {inv['id']} billed ₹{inv['amount']:,.0f} vs contract ₹{c['price']:,.0f}",
                          "fix": "Re-bill the difference"})
            # 3. expired promotions still applied
            if inv.get("discount_applied") and c.get("discount_expires") and _d(c["discount_expires"]) < _d(inv["date"]):
                f.append({"check": "expired_discount", "severity": "medium", "customer": c["customer"], "contract": c["id"],
                          "amount": round(c["price"] * c.get("discount_pct", 0) / 100, 2),
                          "detail": f"promo expired {c['discount_expires']} but still applied on {inv['id']}",
                          "fix": "Remove the discount; bill the difference"})
    # 2. usage vs billing
    for u in usage:
        overage = max(0, u["used_units"] - u["included_units"])
        if overage and u["billed_overage_units"] < overage:
            unb = overage - u["billed_overage_units"]
            f.append({"check": "usage_vs_billing", "severity": "medium", "customer": u["customer"], "contract": u["contract"],
                      "amount": round(unb * u["rate"], 2), "detail": f"{unb} overage units used but not billed",
                      "fix": "Bill overage"})
    # 4. seats
    for s in seats:
        if s["active_seats"] > s["billed_seats"]:
            gap = s["active_seats"] - s["billed_seats"]
            f.append({"check": "seat_mismatch", "severity": "medium", "customer": s["customer"], "contract": s["contract"],
                      "amount": round(gap * s["seat_price"], 2), "detail": f"{s['active_seats']} active vs {s['billed_seats']} billed seats",
                      "fix": "True-up seats"})
    # 5. credits: duplicates or unjustified
    seen = {}
    for cr in credits:
        key = (cr["customer"], round(cr["amount"], 2), cr.get("invoice"))
        if key in seen:
            f.append({"check": "duplicate_credit", "severity": "high", "customer": cr["customer"], "contract": None,
                      "amount": cr["amount"], "detail": f"credit note {cr['id']} duplicates {seen[key]}", "fix": "Reverse duplicate credit"})
        else:
            seen[key] = cr["id"]
        if not cr.get("reason"):
            f.append({"check": "unjustified_credit", "severity": "low", "customer": cr["customer"], "contract": None,
                      "amount": cr["amount"], "detail": f"credit note {cr['id']} has no reason", "fix": "Get approval or reverse"})
    # 6. invoices marked paid without money in
    paid_ids = {p["invoice"] for p in payments}
    for inv in invoices:
        if inv.get("status") == "paid" and inv["id"] not in paid_ids:
            f.append({"check": "paid_without_payment", "severity": "high", "customer": inv.get("customer"), "contract": inv["contract_id"],
                      "amount": inv["amount"], "detail": f"{inv['id']} marked paid but no matching receipt", "fix": "Reconcile with bank/gateway"})
    return sorted(f, key=lambda x: -x["amount"])


# ── B. collections ───────────────────────────────────────────────────────────

class LatenessModel:
    """Expected days-late per payer, shrunk toward the portfolio mean for payers with little history."""

    def __init__(self, shrink: float = 3.0):
        self.by_payer: dict[str, list] = defaultdict(list)
        self.shrink = shrink

    def fit(self, paid_invoices: list[dict]):
        for i in paid_invoices:
            self.by_payer[i["customer"]].append(max(0, (_d(i["paid_at"]) - _d(i["due_date"])).days))
        return self

    def portfolio_mean(self) -> float:
        allv = [v for vs in self.by_payer.values() for v in vs]
        return statistics.mean(allv) if allv else 10.0

    def expected_days_late(self, customer: str) -> float:
        vals = self.by_payer.get(customer, [])
        pm = self.portfolio_mean()
        return (sum(vals) + self.shrink * pm) / (len(vals) + self.shrink)


def collections_worklist(open_invoices: list[dict], model: LatenessModel, today: datetime) -> list[dict]:
    """Rank overdue invoices by ₹ at stake x likelihood of recovery, with channel/tone/timing."""
    rows = []
    for inv in open_invoices:
        overdue = (today - _d(inv["due_date"])).days
        if overdue <= 0:
            continue
        exp_late = model.expected_days_late(inv["customer"])
        p_recover = max(0.05, min(0.97, 0.95 * (0.985 ** max(overdue - exp_late, 0)) * (0.9 if overdue > 90 else 1)))
        tone = "gentle" if overdue <= 7 else ("firm" if overdue <= 30 else "final")
        channel = {"gentle": "email", "firm": "whatsapp", "final": "call"}[tone]
        msme_flag = overdue > MSME_DAYS
        rows.append({"invoice": inv["id"], "customer": inv["customer"], "amount": inv["amount"], "days_overdue": overdue,
                     "expected_days_late": round(exp_late, 1), "p_recover": round(p_recover, 2),
                     "priority_inr": round(inv["amount"] * p_recover, 2), "tone": tone, "channel": channel,
                     "next_action": {"gentle": "Send payment link + friendly reminder", "firm": "WhatsApp with UPI link + promise-to-pay ask",
                                     "final": "Personal call, escalate to account owner"}[tone],
                     "msme_45_day_flag": msme_flag,
                     "msme_note": "Beyond the 45-day norm (verify Section 43B(h) applicability)" if msme_flag else None})
    return sorted(rows, key=lambda r: -r["priority_inr"])


class PromiseTracker:
    def __init__(self):
        self.promises: list[dict] = []

    def log(self, invoice: str, customer: str, amount: float, promised_date: str, channel: str = "call") -> dict:
        p = {"id": f"ptp_{len(self.promises) + 1}", "invoice": invoice, "customer": customer, "amount": amount,
             "promised_date": promised_date, "channel": channel, "status": "open", "logged_at": time.time()}
        self.promises.append(p)
        return p

    def mark(self, pid: str, paid: bool):
        for p in self.promises:
            if p["id"] == pid:
                p["status"] = "kept" if paid else "broken"
                return p
        raise KeyError(pid)

    def due_followups(self, today: datetime) -> list[dict]:
        return [dict(p, follow_up="Promise date passed: follow up now" if _d(p["promised_date"]) <= today else "Upcoming")
                for p in self.promises if p["status"] == "open" and _d(p["promised_date"]) <= today + timedelta(days=1)]

    def reliability(self) -> dict:
        done = [p for p in self.promises if p["status"] in ("kept", "broken")]
        return {"kept": sum(p["status"] == "kept" for p in done), "broken": sum(p["status"] == "broken" for p in done),
                "open": sum(p["status"] == "open" for p in self.promises)}


# ── planted-error demo data ──────────────────────────────────────────────────

def demo_billing_data(seed: int = 7, today: datetime | None = None) -> dict:
    today = today or datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    rng = random.Random(seed)
    names = ["Acme Logistics", "Bluepeak Foods", "Cobalt Systems", "Delta Textiles", "Everest Pharma", "Fable Media",
             "Granite Infra", "Helix Labs", "Indus Retail", "Juno Health", "Kite Analytics", "Lumen Edu"]
    contracts, invoices, usage, seats, credits, payments, open_inv = [], [], [], [], [], [], []
    for i, n in enumerate(names):
        price = rng.choice([25000, 40000, 65000, 90000, 120000])
        c = {"id": f"CT-{i + 1:03d}", "customer": n, "price": price, "cycles_due": 3}
        contracts.append(c)
        for k in range(3):
            date = (today - timedelta(days=30 * (3 - k))).isoformat()[:10]
            inv = {"id": f"INV-{i + 1:03d}-{k + 1}", "contract_id": c["id"], "customer": n, "amount": price,
                   "date": date, "due_date": (today - timedelta(days=30 * (3 - k) - 15)).isoformat()[:10], "status": "paid"}
            invoices.append(inv)
            late = max(0, int(rng.gauss(6 + (i % 4) * 8, 4)))
            paid_at = min(today, today - timedelta(days=30 * (3 - k) - 15 - late))
            inv["paid_at"] = paid_at.isoformat()[:10]
            if paid_at <= today:
                payments.append({"invoice": inv["id"], "amount": price})
    # plant errors
    contracts[1]["cycles_due"] = 4                                                   # a renewal never invoiced
    invoices[7]["amount"] = contracts[2]["price"] * 0.85                              # wrong price applied
    contracts[3].update(discount_pct=15, discount_expires=(today - timedelta(days=75)).isoformat()[:10])
    invoices[10].update(discount_applied=True, amount=contracts[3]["price"] * 0.85)   # expired promo still applied
    usage += [{"customer": names[4], "contract": "CT-005", "used_units": 1800, "included_units": 1000, "billed_overage_units": 200, "rate": 45},
              {"customer": names[6], "contract": "CT-007", "used_units": 5400, "included_units": 5000, "billed_overage_units": 400, "rate": 30}]
    seats += [{"customer": names[5], "contract": "CT-006", "active_seats": 34, "billed_seats": 25, "seat_price": 1200},
              {"customer": names[8], "contract": "CT-009", "active_seats": 12, "billed_seats": 12, "seat_price": 900}]
    credits += [{"id": "CN-101", "customer": names[7], "amount": 8000, "invoice": "INV-008-2", "reason": "service outage"},
                {"id": "CN-102", "customer": names[7], "amount": 8000, "invoice": "INV-008-2", "reason": "service outage"},
                {"id": "CN-103", "customer": names[9], "amount": 5500, "invoice": "INV-010-1", "reason": ""}]
    payments[:] = [p for p in payments if p["invoice"] != "INV-012-3"]                 # marked paid, no money in
    # open receivables
    for i, n in enumerate(names):
        for k in range(rng.choice([0, 1, 2])):
            open_inv.append({"id": f"OPN-{i + 1:03d}-{k + 1}", "customer": n, "amount": rng.choice([18000, 32000, 54000, 88000]),
                             "due_date": (today - timedelta(days=rng.choice([3, 12, 25, 48, 75, 110]))).isoformat()[:10]})
    return {"today": today, "contracts": contracts, "invoices": invoices, "usage": usage, "seats": seats,
            "credits": credits, "payments": payments, "open_invoices": open_inv,
            "paid_history": [i for i in invoices if i["status"] == "paid" and "paid_at" in i]}
