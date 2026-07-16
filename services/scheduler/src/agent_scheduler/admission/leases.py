from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass


@dataclass
class Lease:
    lease_id: str
    resource_class: str
    expires_at: float


class LeaseManager:
    def __init__(self, max_global: int, ttl_ms: int) -> None:
        self.max_global = max_global
        self.ttl_ms = ttl_ms
        self._leases: dict[str, Lease] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, resource_class: str, wait_ms: int) -> str | None:
        deadline = time.monotonic() + wait_ms / 1000
        while True:
            async with self._lock:
                self._expire_locked()
                if len(self._leases) < self.max_global:
                    lease_id = str(uuid.uuid4())
                    self._leases[lease_id] = Lease(
                        lease_id=lease_id,
                        resource_class=resource_class,
                        expires_at=time.monotonic() + self.ttl_ms / 1000,
                    )
                    return lease_id
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.01)

    async def release(self, lease_id: str | None) -> None:
        if lease_id is None:
            return
        async with self._lock:
            self._leases.pop(lease_id, None)

    async def active_count(self) -> int:
        async with self._lock:
            self._expire_locked()
            return len(self._leases)

    def _expire_locked(self) -> None:
        now = time.monotonic()
        expired = [lease_id for lease_id, lease in self._leases.items() if lease.expires_at <= now]
        for lease_id in expired:
            self._leases.pop(lease_id, None)
