"""Webhook ingestion: signature verification, idempotency, dead-letter queue and replay."""

import hashlib
import hmac
import json
import os
import time
import uuid

from .adapters import ADAPTERS, MappingError


class SignatureError(ValueError):
    pass


def compute_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(source: str, body: bytes, signature: str | None, secret: str | None) -> None:
    """Razorpay sends hex HMAC-SHA256 of the body; Stripe sends 't=..,v1=..' over 't.body'."""
    if not secret:
        return  # unsigned demo mode: the connection has no secret configured
    if not signature:
        raise SignatureError("missing signature")
    if source == "stripe" and "v1=" in signature:
        parts = dict(p.split("=", 1) for p in signature.split(",") if "=" in p)
        expected = compute_signature(secret, f"{parts.get('t', '')}.".encode() + body)
        ok = hmac.compare_digest(expected, parts.get("v1", ""))
    else:
        ok = hmac.compare_digest(compute_signature(secret, body), signature)
    if not ok:
        raise SignatureError("invalid signature")


def _event_id(event: dict, body: bytes) -> str:
    return str(event.get("id") or event.get("event_id") or hashlib.sha256(body).hexdigest()[:24])


class IngestionHub:
    def __init__(self, secrets: dict | None = None):
        self.secrets = secrets or {}
        self.raw_events: dict[str, dict] = {}
        self.dead_letters: dict[str, dict] = {}
        self.seen: set[str] = set()
        self.stats = {"received": 0, "processed": 0, "duplicates": 0, "dead_lettered": 0, "bad_signature": 0}
        self.last_event_at: dict[str, float] = {}

    def _secret(self, source: str):
        return self.secrets.get(source) or os.getenv(f"IMPULSE_{source.upper()}_SECRET")

    def receive(self, source: str, body: bytes, signature: str | None = None) -> dict:
        """Verify, dedupe and map one delivery. Returns {status, entities, event_id}."""
        self.stats["received"] += 1
        try:
            verify_signature(source, body, signature, self._secret(source))
        except SignatureError as exc:
            self.stats["bad_signature"] += 1
            return {"status": "rejected", "reason": str(exc), "entities": []}
        try:
            event = json.loads(body)
            if not isinstance(event, dict):
                raise ValueError("payload is not an object")
        except ValueError as exc:
            return self._dead_letter(source, None, body, f"invalid json: {exc}")
        eid = _event_id(event, body)
        key = f"{source}:{eid}"
        if key in self.seen:
            self.stats["duplicates"] += 1
            return {"status": "duplicate", "event_id": eid, "entities": []}
        return self._map(source, key, eid, event, body)

    def _map(self, source: str, key: str, eid: str, event: dict, body: bytes) -> dict:
        self.raw_events[key] = {"source": source, "event": event, "received_at": time.time()}
        adapter = ADAPTERS.get(source)
        try:
            if adapter is None:
                raise MappingError(f"no adapter for source '{source}'")
            entities = adapter(event)
        except (MappingError, KeyError, TypeError, ValueError) as exc:
            return self._dead_letter(source, key, body, str(exc), event=event)
        self.seen.add(key)
        self.stats["processed"] += 1
        self.last_event_at[source] = time.time()
        return {"status": "processed", "event_id": eid, "entities": entities}

    def _dead_letter(self, source, key, body, error, event=None) -> dict:
        dl_id = f"dl_{uuid.uuid4().hex[:10]}"
        self.dead_letters[dl_id] = {"id": dl_id, "source": source, "key": key, "error": error,
                                    "event": event, "raw": body.decode("utf-8", "replace")[:4000],
                                    "at": time.time(), "status": "failed"}
        self.stats["dead_lettered"] += 1
        return {"status": "dead_lettered", "dead_letter_id": dl_id, "error": error, "entities": []}

    def replay(self, dl_id: str, patched_event: dict | None = None) -> dict:
        """Re-run a stored raw event, optionally after the operator patches the payload."""
        dl = self.dead_letters.get(dl_id)
        if not dl:
            raise KeyError(dl_id)
        event = patched_event if patched_event is not None else dl["event"]
        if event is None:
            try:
                event = json.loads(dl["raw"])
            except ValueError:
                return {"status": "dead_lettered", "error": "payload still unparseable", "entities": []}
        body = json.dumps(event).encode()
        eid = _event_id(event, body)
        key = dl["key"] or f"{dl['source']}:{eid}"
        self.seen.discard(key)
        before = set(self.dead_letters)
        res = self._map(dl["source"], key, eid, event, body)
        if res["status"] == "processed":
            del self.dead_letters[dl_id]
            self.stats["dead_lettered"] -= 1
        else:
            # replay failed again: keep the original entry, drop the duplicate _map created
            for new_id in set(self.dead_letters) - before:
                del self.dead_letters[new_id]
                self.stats["dead_lettered"] -= 1
            dl["error"] = res.get("error", dl["error"])
        return res

    def replay_all(self, source: str | None = None) -> list:
        return [self.replay(i) for i, d in list(self.dead_letters.items()) if source in (None, d["source"])]

    def connection_health(self) -> list:
        now = time.time()
        out = []
        for src in ("razorpay", "stripe", "custom"):
            last = self.last_event_at.get(src)
            out.append({"source": src, "signature_verification": bool(self._secret(src)),
                        "last_event_seconds_ago": round(now - last) if last else None,
                        "status": "healthy" if last and now - last < 3600 else ("idle" if last else "no events yet")})
        return out
