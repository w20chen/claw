from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent_scheduler.contracts.models import ToolBeforeRequest, ToolPrediction
from agent_scheduler.predictors.exec_classifier import (
    classify_exec_tool_name,
    extract_exec_operation,
)


@dataclass(frozen=True)
class ToolProfile:
    tool_name: str
    operation: str | None
    resource_class: str
    duration_p50_ms: int
    duration_p90_ms: int


class StaticProfilePredictor:
    def __init__(self, profiles: list[ToolProfile]) -> None:
        self.profiles = profiles

    @classmethod
    def from_path(cls, path: Path | None) -> "StaticProfilePredictor":
        if path is None or not path.exists():
            return cls([])
        data = json.loads(path.read_text(encoding="utf-8"))
        profiles = [ToolProfile(**item) for item in data.get("profiles", [])]
        return cls(profiles)

    async def predict(self, request: ToolBeforeRequest) -> ToolPrediction:
        operation = extract_operation(request)
        profile = self._match(candidate_tool_names(request), operation)
        if profile is None:
            return ToolPrediction(resource_class="unknown")
        confidence = 0.8 if profile.operation else 0.5
        return ToolPrediction(
            duration_p50_ms=profile.duration_p50_ms or None,
            duration_p90_ms=profile.duration_p90_ms or None,
            resource_class=profile.resource_class,
            confidence=confidence,
        )

    def _match(self, tool_names: list[str], operation: str | None) -> ToolProfile | None:
        for tool_name in tool_names:
            for profile in self.profiles:
                if profile.tool_name == tool_name and profile.operation == operation:
                    return profile
        for tool_name in tool_names:
            for profile in self.profiles:
                if profile.tool_name == tool_name and profile.operation is None:
                    return profile
        for profile in self.profiles:
            if profile.tool_name == "*" and profile.operation is None:
                return profile
        return None


def extract_operation(request: ToolBeforeRequest) -> str | None:
    if request.operation_hint:
        return request.operation_hint
    return extract_exec_operation(request.tool_name, request.raw_params)


def candidate_tool_names(request: ToolBeforeRequest) -> list[str]:
    names = [request.tool_name]
    classified = classify_exec_tool_name(request.tool_name, request.raw_params)
    if classified not in names:
        names.insert(0, classified)
    return names
