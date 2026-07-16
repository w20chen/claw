from __future__ import annotations

from agent_scheduler.config import SchedulerConfig


def test_scheduler_config_loads_env_file_and_resolves_paths(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AGENT_SCHEDULER_DB_PATH=data/test.sqlite3",
                "AGENT_SCHEDULER_TRACE_PATH=data/trace.jsonl",
                "AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL=https://example.test/v1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_SCHEDULER_ENV_FILE", str(env_file))
    monkeypatch.delenv("AGENT_SCHEDULER_DB_PATH", raising=False)
    monkeypatch.delenv("AGENT_SCHEDULER_TRACE_PATH", raising=False)
    monkeypatch.delenv("AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL", raising=False)

    config = SchedulerConfig.from_env()

    assert config.db_path == tmp_path / "data" / "test.sqlite3"
    assert config.trace_path == tmp_path / "data" / "trace.jsonl"
    assert config.llm_proxy_upstream_base_url == "https://example.test/v1"
