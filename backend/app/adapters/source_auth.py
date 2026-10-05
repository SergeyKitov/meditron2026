"""Shared HMAC verification for provisional inbound integration adapters."""

import hashlib
import hmac
import os
import re
import time

from app.domain.routing import DomainError

MAX_CLOCK_SKEW_SECONDS = 300
EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
SIGNATURE = re.compile(r"[0-9a-f]{64}\Z")


def verify_hmac_source(config, profile_id, event_id, timestamp, signature, path, body):
    if not config or config.get("auth") != "hmac_sha256":
        raise DomainError("Неизвестный способ проверки источника", 422)
    skew = config.get("max_clock_skew_seconds", MAX_CLOCK_SKEW_SECONDS)
    if type(skew) is not int or not 1 <= skew <= MAX_CLOCK_SKEW_SECONDS:
        raise DomainError("Неверное окно времени для источника", 422)
    secret_env = config.get("secret_env")
    secret = os.getenv(secret_env, "") if secret_env else ""
    if not secret:
        raise DomainError("Секрет источника не настроен", 503)
    if not EVENT_ID.fullmatch(event_id) or not timestamp.isascii() or not timestamp.isdecimal():
        raise DomainError("Неверные заголовки события", 401)
    if abs(int(timestamp) - int(time.time())) > skew:
        raise DomainError("Время события за пределами допустимого окна", 401)
    if not SIGNATURE.fullmatch(signature):
        raise DomainError("Неверная подпись события", 401)
    signed = b"\n".join(
        [timestamp.encode(), profile_id.encode(), event_id.encode(), path.encode(), body]
    )
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise DomainError("Неверная подпись события", 401)
