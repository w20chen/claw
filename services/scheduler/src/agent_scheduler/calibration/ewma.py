from __future__ import annotations

from datetime import datetime, timezone

from agent_scheduler.config import SchedulerConfig
from agent_scheduler.contracts.models import ToolCompletedEvent
from agent_scheduler.storage.sqlite import SQLiteStore


class EWMACalibrator:
    def __init__(self, store: SQLiteStore, config: SchedulerConfig) -> None:
        self.store = store
        self.config = config

    def update(self, completion: ToolCompletedEvent, predicted_ms: int | None) -> bool:
        if predicted_ms is None or predicted_ms <= 0 or completion.duration_ms <= 0:
            return False
        ratio = completion.duration_ms / predicted_ms
        ratio = max(self.config.calibration_min_ratio, min(self.config.calibration_max_ratio, ratio))
        key = completion.tool_name
        old = self.store.get_calibration(key) or 1.0
        new = (1 - self.config.calibration_alpha) * old + self.config.calibration_alpha * ratio
        self.store.update_calibration(key, new, datetime.now(timezone.utc).isoformat())
        return True
