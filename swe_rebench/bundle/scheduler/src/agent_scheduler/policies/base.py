from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_scheduler.contracts.models import PlacementAdvice, ToolBeforeRequest, ToolDecision, ToolPrediction


@dataclass
class SchedulingContext:
    prediction: ToolPrediction
    placement: PlacementAdvice


class SchedulingPolicy(Protocol):
    async def decide(self, request: ToolBeforeRequest, context: SchedulingContext) -> ToolDecision:
        ...
