"""HMAC contract for incoming booking statuses.

The integration secret is supplied by the deployment environment, never by
the clinic profile file or the browser. The demo feedback endpoint is separate.
"""

from app.adapters.source_auth import verify_hmac_source
from app.domain.routing import DomainError


def verify_booking_webhook(profile, profile_id, event_id, timestamp, signature, path, body):
    if profile.get("booking_mode") != "deferred_simulator":
        raise DomainError("Профиль не принимает отложенный статус записи", 403)
    verify_hmac_source(
        profile.get("booking_callback"), profile_id, event_id, timestamp, signature, path, body
    )
