from __future__ import annotations

import uuid

from agent_scheduler.admission.leases import LeaseManager
from agent_scheduler.contracts.models import ToolBeforeRequest, ToolDecision
from agent_scheduler.policies.base import SchedulingContext


class ConcurrencyPolicy:
    name = "concurrency"
    version = "1"

    def __init__(self, leases: LeaseManager, admission_wait_ms: int) -> None:
        self.leases = leases
        self.admission_wait_ms = admission_wait_ms

    async def decide(self, request: ToolBeforeRequest, context: SchedulingContext) -> ToolDecision:
        lease_id = await self.leases.acquire(context.prediction.resource_class, self.admission_wait_ms)
        if lease_id is None:
            return ToolDecision(
                decision_id=str(uuid.uuid4()),
                action="block",
                reason_code="admission_timeout",
                reason="Admission wait limit elapsed before a lease became available.",
                policy_name=self.name,
                policy_version=self.version,
                lease_id=None,
                prediction=context.prediction,
                placement_advice=context.placement,
            )
        return ToolDecision(
            decision_id=str(uuid.uuid4()),
            action="allow",
            reason_code="lease_acquired",
            reason="A bounded concurrency lease was acquired.",
            policy_name=self.name,
            policy_version=self.version,
            lease_id=lease_id,
            prediction=context.prediction,
            placement_advice=context.placement,
        )
