"""Booking boundary used by the synthetic demo profiles.

Adapters only prepare local requests. A real clinic adapter must send its request
after commit and authenticate replies; neither transport is implemented here.
"""

from dataclasses import dataclass
from typing import Protocol

from app.domain.routing import DomainError


@dataclass(frozen=True)
class BookingReceipt:
    status: str
    external_ref: str
    needs_dispatch: bool


class BookingAdapter(Protocol):
    def prepare(self, booking_id: str) -> BookingReceipt: ...


class LocalSimulator:
    def prepare(self, booking_id: str) -> BookingReceipt:
        return BookingReceipt("confirmed", f"DEMO-{booking_id[:8]}", False)


class DeferredSimulator:
    def prepare(self, booking_id: str) -> BookingReceipt:
        return BookingReceipt("requested", f"REQ-{booking_id}", True)


def adapter_for(profile: dict) -> BookingAdapter:
    mode = profile.get("booking_mode", "local_simulator")
    if mode == "local_simulator":
        return LocalSimulator()
    if mode == "deferred_simulator":
        return DeferredSimulator()
    raise DomainError(f"Неизвестный режим записи: {mode}", 422)
