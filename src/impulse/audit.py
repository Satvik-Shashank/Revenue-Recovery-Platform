"""Leak Audit: upload 90 days of exports, see what leaked and what Impulse would have recovered.

Every recoverable-₹ figure is an ESTIMATE built from labelled assumptions (see `assumptions` in the report),
not a promise. Payment-recovery rates come from the Replay Lab's simulated world."""

import html
import io
import json
import os
import random
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import pandas as pd

from .declines import CATEGORY, normalize_decline

KINDS = {
    "payments": {"customer": ["customer", "customer_id", "email", "contact", "user"],
                 "amount": ["amount", "value", "txn amount", "total"],
                 "status": ["status", "state", "result", "payment status"],
                 "decline_code": ["decline code", "error code", "failure reason", "error reason", "failure code", "error"],
                 "date": ["date", "created at", "created", "timestamp", "attempted at"],
                 "gateway": ["gateway", "provider", "processor"], "method": ["method", "payment method", "mode"],
                 "order_id": ["order id", "order", "invoice id", "reference"], "recurring": ["recurring", "is recurring", "subscription"]},
    "disputes": {"customer": ["customer", "customer_id", "email"], "amount": ["amount", "dispute amount"],
                 "status": ["status", "outcome", "result"], "reason_code": ["reason code", "reason", "code"],
                 "date": ["date", "opened at", "created"]},
    "refunds": {"customer": ["customer", "customer_id", "email"], "amount": ["amount", "refund amount"],
                "reason": ["reason", "refund reason"], "date": ["date", "requested at", "created"]},
    "subscriptions": {"customer": ["customer", "customer_id", "email"], "amount": ["amount", "mrr", "price", "monthly amount"],
                      "status": ["status", "state"], "last_payment_status": ["last payment status", "last payment", "last charge"],
                      "canceled_at": ["canceled at", "cancelled at", "ended at"]},
    "invoices": {"customer": ["customer", "customer_id", "email"], "amount": ["amount", "amount due", "total"],
                 "due_date": ["due date", "due", "due_at"], "paid_at": ["paid at", "paid date", "payment date"],
                 "status": ["status", "state"]},
}
REQUIRED = {"payments": ["amount", "status"], "disputes": ["amount"], "refunds": ["amount"],
            "subscriptions": ["amount", "status"], "invoices": ["amount", "due_date"]}
FAIL = {"failed", "fail", "declined", "failure", "error", "unsuccessful"}
OK = {"success", "succeeded", "captured", "paid", "authorized", "completed"}

# labelled modelling assumptions
ASSUMPTIONS = {
    "impulse_payment_recovery_rate": "from the Replay Lab (simulated world); falls back to 0.65",
    "assumed_merchant_baseline_recovery": 0.35,
    "dispute_contestable_share": 0.60,
    "dispute_win_rate_when_fought": 0.35,
    "serial_refunder_min_refunds": 3,
    "serial_refund_recoverable_share": 0.5,
    "involuntary_churn_recoverable_share": 0.35,
    "voluntary_churn_recoverable_share": 0.05,
    "overdue_recoverable_share": 0.60,
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def auto_map(df: pd.DataFrame, kind: str) -> dict:
    """Map our canonical fields to the file's columns. Returns {field: {column, confidence}}."""
    cols = {_norm(c): c for c in df.columns}
    out = {}
    for field, aliases in KINDS[kind].items():
        best, score = None, 0.0
        for cand in [field.replace("_", " ")] + aliases:
            n = _norm(cand)
            if n in cols:
                best, score = cols[n], 1.0
                break
            for cn, orig in cols.items():
                r = SequenceMatcher(None, n, cn).ratio()
                if (n in cn or cn in n) and min(len(n), len(cn)) >= 4:
                    r = max(r, 0.85)
                if r > score:
                    best, score = orig, r
        out[field] = {"column": best if score >= 0.75 else None, "confidence": round(score, 2) if score >= 0.75 else 0.0}
    return out


def apply_mapping(df: pd.DataFrame, kind: str, mapping: dict | None) -> tuple[pd.DataFrame, dict, list]:
    """Rename to canonical fields. `mapping` = manual override {field: column}. Returns (df, used_map, problems)."""
    auto = auto_map(df, kind)
    used = {f: (mapping or {}).get(f) or v["column"] for f, v in auto.items()}
    problems = [f"missing required field '{f}'" for f in REQUIRED[kind] if not used.get(f) or used[f] not in df.columns]
    out = pd.DataFrame({f: df[c] for f, c in used.items() if c in df.columns})
    if "amount" in out:
        out["amount"] = pd.to_numeric(out["amount"].astype(str).str.replace(r"[^\d.\-]", "", regex=True), errors="coerce")
        bad = int(out["amount"].isna().sum())
        if bad:
            problems.append(f"{bad} rows have an unreadable amount and were dropped")
        out = out.dropna(subset=["amount"])
    for dc in ("date", "due_date", "paid_at", "canceled_at"):
        if dc in out:
            out[dc] = pd.to_datetime(out[dc], errors="coerce", utc=True)
    return out, used, problems


def _impulse_rates() -> tuple[float, float]:
    try:
        from .sim import cached_replay
        r = cached_replay()["policies"]
        return r["impulse"]["recovery_rate"]["mean"], r["baseline"]["recovery_rate"]["mean"]
    except Exception:
        return 0.65, 0.45


def run_audit(frames: dict[str, pd.DataFrame], mappings: dict | None = None) -> dict:
    """frames: {'payments': df, 'disputes': df, ...}. Returns the audit report dict."""
    mappings = mappings or {}
    clean, used_maps, problems = {}, {}, []
    for kind, df in frames.items():
        if kind not in KINDS or df is None or df.empty:
            continue
        c, m, p = apply_mapping(df, kind, mappings.get(kind))
        clean[kind], used_maps[kind] = c, m
        problems += [f"{kind}: {x}" for x in p]
    imp_rate, base_rate_sim = _impulse_rates()
    A = ASSUMPTIONS
    leaks = {"failed": 0.0, "clawed_back": 0.0, "stopped": 0.0, "missed": 0.0}
    recov = dict(leaks)
    findings, customers = [], {}

    def expose(cust, amt, cause):
        if cust is None or (isinstance(cust, float) and pd.isna(cust)):
            return
        e = customers.setdefault(str(cust), {"customer": str(cust), "exposure": 0.0, "causes": set()})
        e["exposure"] += amt
        e["causes"].add(cause)

    # ── failed ──
    pay = clean.get("payments")
    if pay is not None and "status" in pay:
        st = pay["status"].astype(str).str.lower().str.strip()
        failed = pay[st.isin(FAIL)].copy()
        total_failed = float(failed["amount"].sum())
        recovered_share = A["assumed_merchant_baseline_recovery"]
        basis = "assumed"
        if "order_id" in pay and len(failed):
            ok_orders = set(pay[st.isin(OK)]["order_id"].dropna().astype(str))
            f_orders = failed["order_id"].dropna().astype(str)
            if len(f_orders):
                recovered_share = float(f_orders.isin(ok_orders).mean())
                basis = "observed (failed orders later paid)"
        leaks["failed"] = total_failed * (1 - recovered_share)
        recov["failed"] = total_failed * max(0.0, imp_rate - recovered_share)
        if len(failed):
            if "decline_code" in failed:
                cats = failed["decline_code"].map(lambda r: normalize_decline("razorpay", r)[1] if isinstance(r, str) else "soft")
                by_cat = failed.assign(cat=cats).groupby("cat")["amount"].agg(["sum", "count"])
                for cat, row in by_cat.iterrows():
                    findings.append({"leak": "failed", "text": f"{int(row['count'])} {cat}-decline payments worth ₹{row['sum']:,.0f}",
                                     "amount": float(row["sum"])})
                hard = float(by_cat["sum"].get("hard", 0))
                if hard:
                    findings.append({"leak": "failed", "amount": hard,
                                     "text": f"₹{hard:,.0f} sits in hard declines: retries can never recover it, but update-link and UPI fallback can"})
            findings.append({"leak": "failed", "amount": total_failed, "text":
                             f"Payment recovery is {recovered_share:.0%} ({basis}); the simulated Impulse policy reaches ~{imp_rate:.0%}"})
            if "customer" in failed:
                for cust, amt in failed.groupby("customer")["amount"].sum().items():
                    expose(cust, amt * (1 - recovered_share), "failed")

    # ── clawed back ──
    dis = clean.get("disputes")
    if dis is not None:
        lost_mask = dis["status"].astype(str).str.lower().isin({"lost", "accepted", "conceded", "closed lost"}) if "status" in dis else pd.Series(True, index=dis.index)
        lost = dis[lost_mask]
        leaks["clawed_back"] += float(lost["amount"].sum())
        recov["clawed_back"] += float(lost["amount"].sum()) * A["dispute_contestable_share"] * A["dispute_win_rate_when_fought"]
        findings.append({"leak": "clawed_back", "amount": float(lost["amount"].sum()),
                         "text": f"{len(lost)} disputes lost or conceded worth ₹{lost['amount'].sum():,.0f}; "
                                 f"~{A['dispute_contestable_share']:.0%} are contestable with the right evidence"})
        if "customer" in lost:
            for cust, amt in lost.groupby("customer")["amount"].sum().items():
                expose(cust, amt, "clawed_back")
    ref = clean.get("refunds")
    if ref is not None:
        total_ref = float(ref["amount"].sum())
        leaks["clawed_back"] += total_ref * 0.15  # only the abusive-looking share is counted as a leak
        if "customer" in ref:
            counts = ref.groupby("customer")["amount"].agg(["count", "sum"])
            serial = counts[counts["count"] >= A["serial_refunder_min_refunds"]]
            recov["clawed_back"] += float(serial["sum"].sum()) * A["serial_refund_recoverable_share"]
            leaks["clawed_back"] += float(serial["sum"].sum()) * A["serial_refund_recoverable_share"]
            if len(serial):
                findings.append({"leak": "clawed_back", "amount": float(serial["sum"].sum()),
                                 "text": f"{len(serial)} customers requested ≥{A['serial_refunder_min_refunds']} refunds (₹{serial['sum'].sum():,.0f}): "
                                         "candidates for abuse scoring and no win-back discounts"})
                for cust, row in serial.iterrows():
                    expose(cust, row["sum"] * 0.5, "clawed_back")

    # ── stopped ──
    sub = clean.get("subscriptions")
    if sub is not None and "status" in sub:
        canceled = sub[sub["status"].astype(str).str.lower().isin({"canceled", "cancelled", "churned", "ended"})]
        if "last_payment_status" in canceled:
            invol_mask = canceled["last_payment_status"].astype(str).str.lower().isin(FAIL)
        else:
            invol_mask = pd.Series(False, index=canceled.index)
        invol, vol = canceled[invol_mask], canceled[~invol_mask]
        arr_i, arr_v = float(invol["amount"].sum()) * 12, float(vol["amount"].sum()) * 12
        leaks["stopped"] = arr_i + arr_v
        recov["stopped"] = arr_i * A["involuntary_churn_recoverable_share"] + arr_v * A["voluntary_churn_recoverable_share"]
        findings.append({"leak": "stopped", "amount": arr_i + arr_v,
                         "text": f"{len(canceled)} cancelled subscriptions = ₹{arr_i + arr_v:,.0f} annual revenue; {len(invol)} "
                                 f"({arr_i:,.0f}/yr) followed a failed payment, i.e. involuntary churn that a payment fix can win back"})
        if "customer" in canceled:
            for cust, amt in canceled.groupby("customer")["amount"].sum().items():
                expose(cust, amt * 12, "stopped")

    # ── missed ──
    inv = clean.get("invoices")
    if inv is not None:
        today = pd.Timestamp.now(tz="UTC")
        unpaid = inv[inv["paid_at"].isna()] if "paid_at" in inv else inv
        if "status" in inv and "paid_at" not in inv:
            unpaid = inv[~inv["status"].astype(str).str.lower().isin(OK)]
        overdue = unpaid[unpaid["due_date"] < today] if "due_date" in unpaid else unpaid
        leaks["missed"] = float(overdue["amount"].sum())
        recov["missed"] = leaks["missed"] * A["overdue_recoverable_share"]
        findings.append({"leak": "missed", "amount": leaks["missed"],
                         "text": f"{len(overdue)} overdue invoices worth ₹{leaks['missed']:,.0f} (collections worklist would prioritise by ₹ x likelihood)"})
        if "customer" in overdue:
            for cust, amt in overdue.groupby("customer")["amount"].sum().items():
                expose(cust, amt, "missed")

    total_leak, total_rec = sum(leaks.values()), sum(recov.values())
    top = sorted(findings, key=lambda f: -f["amount"])[:6]
    sample = sorted(customers.values(), key=lambda c: -c["exposure"])[:8]
    for s in sample:
        s["causes"] = sorted(s["causes"])
        s["exposure"] = round(s["exposure"], 2)
    return {
        "headline": f"You leaked ₹{total_leak:,.0f}. Impulse would have recovered an estimated ₹{total_rec:,.0f}.",
        "total_leak": round(total_leak, 2), "estimated_recoverable": round(total_rec, 2),
        "by_cause": {k: {"leaked": round(leaks[k], 2), "recoverable": round(recov[k], 2)} for k in leaks},
        "top_findings": [{"leak": f["leak"], "text": f["text"]} for f in top], "sample_customers": sample,
        "mapping": used_maps, "problems": problems, "assumptions": ASSUMPTIONS,
        "rows_analysed": {k: int(len(v)) for k, v in clean.items()},
        "disclosure": "Estimates use labelled assumptions and a simulated recovery model; validate on your own outcomes.",
    }


def render_report_html(rep: dict, merchant: str = "Your business") -> str:
    """Self-contained, print-friendly page: use the browser's 'Save as PDF'."""
    e = html.escape
    rows = "".join(f"<tr><td>{e(k.replace('_', ' ').title())}</td><td>₹{v['leaked']:,.0f}</td><td>₹{v['recoverable']:,.0f}</td></tr>"
                   for k, v in rep["by_cause"].items())
    finds = "".join(f"<li>{e(f['text'])}</li>" for f in rep["top_findings"])
    cust = "".join(f"<tr><td>{e(c['customer'])}</td><td>₹{c['exposure']:,.0f}</td><td>{e(', '.join(c['causes']))}</td></tr>" for c in rep["sample_customers"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Revenue Leak Audit</title>
<style>body{{font:15px/1.5 -apple-system,Segoe UI,sans-serif;max-width:780px;margin:32px auto;padding:0 20px;color:#1a1f36}}
h1{{font-size:26px;margin:0 0 4px}}.big{{font-size:20px;font-weight:600;background:#eef2ff;padding:16px;border-radius:10px;margin:18px 0}}
table{{border-collapse:collapse;width:100%;margin:10px 0 22px}}td,th{{border-bottom:1px solid #e3e8ee;padding:8px;text-align:left}}
small{{color:#697386}}@media print{{body{{margin:0}}}}</style></head><body>
<h1>Revenue Leak Audit</h1><small>{e(merchant)} · generated {datetime.now(timezone.utc).strftime('%d %b %Y')}</small>
<div class="big">{e(rep['headline'])}</div>
<h2>Leak by cause</h2><table><tr><th>Cause</th><th>Leaked</th><th>Estimated recoverable</th></tr>{rows}</table>
<h2>Top findings</h2><ul>{finds}</ul>
<h2>Customers with the most exposure</h2><table><tr><th>Customer</th><th>Exposure</th><th>Causes</th></tr>{cust}</table>
<p><small>{e(rep['disclosure'])}</small></p></body></html>"""


def sample_audit_data(seed: int = 11) -> dict[str, pd.DataFrame]:
    """A messy-but-plausible 90-day export set for the demo (deliberately awkward column names)."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    codes = [("insufficient_funds", .38), ("do_not_honor", .16), ("expired_card", .14), ("bank_downtime", .10),
             ("authentication_failed", .08), ("limit_exceeded", .06), ("card_lost", .03), ("invalid_card_number", .05)]
    customers = [f"cust{rng.randint(1000, 1400)}@example.in" for _ in range(320)]
    rows = []
    for i in range(1800):
        c = rng.choice(customers)
        d = now - timedelta(days=rng.random() * 90)
        ok = rng.random() < 0.87
        code = rng.choices([x for x, _ in codes], [w for _, w in codes])[0]
        amt = round(rng.lognormvariate(7.1, 0.7), 2)
        rows.append({"Txn ID": f"pay_{i}", "Customer Email": c, "Txn Amount": f"₹{amt:,.2f}", "Payment Status": "captured" if ok else "failed",
                     "Error Reason": "" if ok else code, "Created At": d.isoformat(), "Order Reference": f"ord_{i}", "Provider": rng.choice(["razorpay", "stripe"]),
                     "Payment Method": rng.choice(["card", "card", "upi", "netbanking"])})
    pay = pd.DataFrame(rows)
    failed_ids = pay[pay["Payment Status"] == "failed"]["Order Reference"].sample(frac=0.3, random_state=seed)
    extra = pay[pay["Order Reference"].isin(failed_ids)].copy()
    extra["Payment Status"], extra["Error Reason"], extra["Txn ID"] = "captured", "", "retry_" + extra["Txn ID"]
    pay = pd.concat([pay, extra], ignore_index=True)
    dis = pd.DataFrame([{"Customer Email": rng.choice(customers), "Dispute Amount": round(rng.lognormvariate(8, .8), 2),
                         "Outcome": rng.choices(["lost", "won", "accepted"], [.55, .2, .25])[0], "Reason": rng.choice(["13.1", "10.4", "4855", "13.3"]),
                         "Opened At": (now - timedelta(days=rng.random() * 90)).isoformat()} for _ in range(45)])
    serial = rng.sample(customers, 6)
    ref = pd.DataFrame([{"Customer Email": (rng.choice(serial) if rng.random() < .35 else rng.choice(customers)),
                         "Refund Amount": round(rng.lognormvariate(7, .7), 2), "Reason": rng.choice(["not received", "not as described", "changed mind"]),
                         "Requested At": (now - timedelta(days=rng.random() * 90)).isoformat()} for _ in range(120)])
    subs = pd.DataFrame([{"Customer Email": c, "MRR": rng.choice([499, 999, 1999, 4999]),
                          "State": rng.choices(["active", "canceled"], [.85, .15])[0],
                          "Last Payment": rng.choices(["succeeded", "failed"], [.5, .5])[0]} for c in customers])
    invs = pd.DataFrame([{"Customer Email": rng.choice(customers), "Amount Due": rng.choice([18000, 32000, 54000]),
                          "Due Date": (now - timedelta(days=rng.randint(-10, 100))).isoformat(),
                          "Paid Date": None if rng.random() < .3 else (now - timedelta(days=rng.randint(0, 40))).isoformat()} for _ in range(60)])
    return {"payments": pay, "disputes": dis, "refunds": ref, "subscriptions": subs, "invoices": invs}
