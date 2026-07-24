from __future__ import annotations

from agent_scheduler.config import SchedulerConfig


def test_scheduler_config_loads_env_file_and_resolves_paths(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AGENT_SCHEDULER_TRACE_DIR=data/traces",
                "AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL=https://example.test/v1",
                "AGENT_SCHEDULER_LLM_PROXY_DEBUG_DUMP=true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_SCHEDULER_ENV_FILE", str(env_file))
    monkeypatch.delenv("AGENT_SCHEDULER_TRACE_DIR", raising=False)
    monkeypatch.delenv("AGENT_SCHEDULER_LLM_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_SCHEDULER_LLM_PROXY_DEBUG_DUMP", raising=False)

    config = SchedulerConfig.from_env()

    assert config.trace_dir == tmp_path / "data" / "traces"
    assert config.llm_proxy_upstream_base_url == "https://example.test/v1"
    assert config.llm_proxy_debug_dump is True
