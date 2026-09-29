"""Identity resolution: recognise one customer across gateways and tools.

Deterministic keys (email, phone, card fingerprint) merge automatically.
Probabilistic matches (name + address similarity) are only *suggested* for a human.
Every merge/unmerge is recorded in an audit trail.
"""

import re
import time
from difflib import SequenceMatcher


def norm_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.strip().lower().split("@", 1)
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
    return f"{local}@{domain}"


def norm_phone(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else None


class IdentityResolver:
    def __init__(self):
        self.parent: dict[str, str] = {}          # union-find over canonical ids
        self.key_owner: dict[str, str] = {}       # deterministic key -> first customer id
        self.profiles: dict[str, dict] = {}       # canonical id -> merged profile
        self.members: dict[str, set] = {}         # canonical id -> provisional ids
        self.audit: list[dict] = []
        self._merge_log: dict[str, dict] = {}     # merge_id -> snapshot for unmerge
        self.suggestions: list[dict] = []
        self._blocks: dict[str, set] = {}          # surname -> provisional ids (blocking for probabilistic matching)

    # ── union-find ──
    def _find(self, x: str) -> str:
        while self.parent.setdefault(x, x) != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def canonical(self, provisional_id: str) -> str:
        return self._find(provisional_id)

    def _keys(self, cust, fingerprint: str | None = None) -> list[str]:
        keys = []
        if (e := norm_email(getattr(cust, "email", None))):
            keys.append(f"email:{e}")
        if (p := norm_phone(getattr(cust, "phone", None))):
            keys.append(f"phone:{p}")
        if fingerprint:
            keys.append(f"fp:{fingerprint}")
        return keys

    def resolve(self, cust, fingerprint: str | None = None) -> str:
        """Register a Customer entity (+ optional card fingerprint); returns canonical id."""
        cid = cust.id
        root = self._find(cid)
        prof = self.profiles.setdefault(root, {"id": root, "name": None, "email": None, "phone": None,
                                               "source_ids": {}, "address": None, "created_at": None})
        self.members.setdefault(root, set()).add(cid)
        for k, v in (("name", cust.name), ("email", cust.email), ("phone", cust.phone), ("address", cust.address),
                     ("created_at", cust.created_at)):
            prof[k] = prof[k] or v
        prof["source_ids"].update(cust.source_ids or {})
        for key in self._keys(cust, fingerprint):
            owner = self.key_owner.setdefault(key, root)
            owner_root = self._find(owner)
            if owner_root != self._find(cid):
                self._merge(owner_root, self._find(cid), reason=f"deterministic match on {key.split(':')[0]}", auto=True)
        self._suggest(self._find(cid))
        return self._find(cid)

    def register_fingerprint(self, customer_id: str, fingerprint: str | None) -> str:
        if not fingerprint:
            return self._find(customer_id)
        key = f"fp:{fingerprint}"
        root = self._find(customer_id)
        owner_root = self._find(self.key_owner.setdefault(key, root))
        if owner_root != root:
            self._merge(owner_root, root, reason="deterministic match on card fingerprint", auto=True)
        return self._find(customer_id)

    def _merge(self, a: str, b: str, reason: str, auto: bool, actor: str = "system") -> str:
        a, b = self._find(a), self._find(b)
        if a == b:
            return a
        merge_id = f"mrg_{len(self._merge_log) + 1}"
        self._merge_log[merge_id] = {"keep": a, "absorbed": b, "profile_b": dict(self.profiles.get(b, {})),
                                     "members_b": set(self.members.get(b, {b}))}
        self.parent[b] = a
        pa, pb = self.profiles.setdefault(a, {"id": a, "source_ids": {}}), self.profiles.pop(b, {})
        for k, v in pb.items():
            if k == "source_ids":
                pa.setdefault("source_ids", {}).update(v)
            elif not pa.get(k):
                pa[k] = v
        self.members.setdefault(a, set()).update(self.members.pop(b, {b}))
        self.audit.append({"id": merge_id, "action": "merge", "keep": a, "absorbed": b, "reason": reason,
                           "auto": auto, "actor": actor, "at": time.time()})
        return a

    def merge(self, a: str, b: str, actor: str = "analyst") -> str:
        """Human-approved merge (typically from a suggestion)."""
        keep = self._merge(a, b, reason="approved by human", auto=False, actor=actor)
        self.suggestions = [s for s in self.suggestions if {s["a"], s["b"]} != {a, b}]
        return keep

    def unmerge(self, merge_id: str, actor: str = "analyst") -> dict:
        snap = self._merge_log.get(merge_id)
        if not snap:
            raise KeyError(merge_id)
        keep, absorbed = snap["keep"], snap["absorbed"]
        for m in snap["members_b"]:
            self.parent[m] = absorbed
        self.parent[absorbed] = absorbed
        self.members[keep] = self.members.get(keep, set()) - snap["members_b"]
        self.members[absorbed] = set(snap["members_b"])
        self.profiles[absorbed] = snap["profile_b"] or {"id": absorbed, "source_ids": {}}
        # deterministic keys that pointed at the absorbed identity stay attached to it
        self.audit.append({"id": f"un_{merge_id}", "action": "unmerge", "keep": keep, "absorbed": absorbed,
                           "actor": actor, "at": time.time()})
        return {"restored": absorbed, "kept": keep}

    def _suggest(self, root: str):
        me = self.profiles.get(root)
        if not me or not me.get("name"):
            return
        block = self._blocks.setdefault(me["name"].lower().split()[-1], set())
        block.add(root)
        for other in {self._find(o) for o in block}:
            prof = self.profiles.get(other)
            if other == root or not prof or not prof.get("name"):
                continue
            name_sim = SequenceMatcher(None, me["name"].lower(), prof["name"].lower()).ratio()
            addr_sim = SequenceMatcher(None, (me.get("address") or "").lower(), (prof.get("address") or "").lower()).ratio()                 if me.get("address") and prof.get("address") else 0.0
            score = 0.6 * name_sim + 0.4 * addr_sim
            if name_sim >= 0.85 and score >= 0.8 and not any({s["a"], s["b"]} == {root, other} for s in self.suggestions):
                self.suggestions.append({"a": root, "b": other, "score": round(score, 2),
                                         "reason": f"name {name_sim:.0%} / address {addr_sim:.0%} similar"})

    def profile(self, customer_id: str) -> dict:
        root = self._find(customer_id)
        return {**self.profiles.get(root, {"id": root}), "linked_ids": sorted(self.members.get(root, {root}))}
