"""Outcome Ledger: hash-chained, decision-receipt-bearing record of every action and result.

Attribution rule: only revenue that would NOT have been recovered under the merchant's baseline
counts. Treatment cases are credited (recovered - baseline expectation); a holdout arm left on the
merchant's original logic measures that baseline honestly."""

import csv
import hashlib
import io
import json
import time
from collections import defaultdict

GENESIS = "0" * 64


def _hash(prev: str, body: dict) -> str:
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest()


class Ledger:
    DEFAULT_BASELINES = {"payments": 0.35, "clawback": 0.05, "retention": 0.05, "refunds": 0.0, "rto": 0.0}

    def __init__(self, fee_pct: float = 12.0, default_baseline_rate: float = 0.20, min_holdout: int = 20):
        self.default_baselines = dict(self.DEFAULT_BASELINES)
        self.entries: list[dict] = []
        self.fee_pct = fee_pct
        self.default_baseline_rate = default_baseline_rate
        self.min_holdout = min_holdout

    def record(self, *, case_id: str, module: str, action: str, amount_at_stake: float, recovered: float,
               cost: float = 0.0, arm: str = "treatment", customer_id: str | None = None,
               receipt: dict | None = None, at: float | None = None) -> dict:
        """Append one row. `receipt` carries the decision inputs, model versions, reason, rejected alternatives."""
        body = {"seq": len(self.entries) + 1, "case_id": case_id, "module": module, "action": action,
                "arm": arm, "customer_id": customer_id, "amount_at_stake": round(amount_at_stake, 2),
                "recovered": round(recovered, 2), "cost": round(cost, 2), "at": at or time.time(),
                "receipt": receipt or {}}
        prev = self.entries[-1]["hash"] if self.entries else GENESIS
        body["prev_hash"] = prev
        body["hash"] = _hash(prev, {k: v for k, v in body.items() if k not in ("hash",)})
        self.entries.append(body)
        return body

    def verify_chain(self) -> dict:
        prev = GENESIS
        for e in self.entries:
            body = {k: v for k, v in e.items() if k != "hash"}
            if e["prev_hash"] != prev or _hash(prev, body) != e["hash"]:
                return {"valid": False, "broken_at": e["seq"], "entries": len(self.entries)}
            prev = e["hash"]
        return {"valid": True, "broken_at": None, "entries": len(self.entries), "head": prev}

    # ── attribution ──
    def baseline_rate(self, module: str) -> tuple[float, str]:
        hold = [e for e in self.entries if e["module"] == module and e["arm"] == "holdout" and e["amount_at_stake"] > 0]
        if len(hold) >= self.min_holdout:
            return sum(e["recovered"] for e in hold) / sum(e["amount_at_stake"] for e in hold), "holdout"
        return self.default_baselines.get(module, self.default_baseline_rate), "assumed"

    def summary(self, module: str | None = None) -> dict:
        rows = [e for e in self.entries if module in (None, e["module"])]
        by_module: dict = {}
        for m in sorted({e["module"] for e in rows}):
            rate, basis = self.baseline_rate(m)
            treat = [e for e in rows if e["module"] == m and e["arm"] == "treatment"]
            hold = [e for e in rows if e["module"] == m and e["arm"] == "holdout"]
            gross = sum(e["recovered"] for e in treat)
            baseline_expect = sum(e["amount_at_stake"] * rate for e in treat)
            cost = sum(e["cost"] for e in treat)
            incr = gross - baseline_expect
            net = incr - cost
            by_module[m] = {"cases": len(treat), "holdout_cases": len(hold), "gross_recovered": round(gross, 2),
                            "baseline_expected": round(baseline_expect, 2), "incremental": round(incr, 2),
                            "cost": round(cost, 2), "net": round(net, 2), "baseline_rate": round(rate, 4),
                            "baseline_basis": basis,
                            "treatment_rate": round(gross / max(sum(e["amount_at_stake"] for e in treat), 1), 4)}
        total_net = sum(v["net"] for v in by_module.values())
        gross_total = sum(v["gross_recovered"] for v in by_module.values())
        fee = max(0.0, total_net) * self.fee_pct / 100
        return {"by_module": by_module, "gross_recovered": round(gross_total, 2), "net_incremental": round(total_net, 2),
                "fee_pct": self.fee_pct, "impulse_fee": round(fee, 2), "merchant_net_gain": round(total_net - fee, 2),
                "entries": len(self.entries)}

    def by_action(self) -> list[dict]:
        agg = defaultdict(lambda: {"cases": 0, "recovered": 0.0, "cost": 0.0})
        for e in self.entries:
            if e["arm"] != "treatment":
                continue
            a = agg[(e["module"], e["action"])]
            a["cases"] += 1
            a["recovered"] += e["recovered"]
            a["cost"] += e["cost"]
        return sorted([{"module": m, "action": ac, "cases": v["cases"], "recovered": round(v["recovered"], 2),
                        "cost": round(v["cost"], 2), "net": round(v["recovered"] - v["cost"], 2)}
                       for (m, ac), v in agg.items()], key=lambda r: -r["net"])

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["seq", "time", "case_id", "customer_id", "module", "action", "arm", "amount_at_stake",
                    "recovered", "cost", "net", "reason", "hash"])
        for e in self.entries:
            w.writerow([e["seq"], time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(e["at"])), e["case_id"], e["customer_id"],
                        e["module"], e["action"], e["arm"], e["amount_at_stake"], e["recovered"], e["cost"],
                        round(e["recovered"] - e["cost"], 2), (e["receipt"] or {}).get("reason", ""), e["hash"]])
        return buf.getvalue()
