from __future__ import annotations

from typing import Any

import pytest

from agent_scheduler import launcher


class _FakeChild:
    pid = 4242

    def wait(self) -> int:
        return 7


def test_launcher_claims_starts_and_returns_child_exit_code(monkeypatch) -> None:
    posts: list[tuple[str, dict[str, Any]]] = []

    def fake_post_json(_endpoint: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        posts.append((path, payload))
        assert path == "/v2/executions/claim"
        return {
            "execution_id": "exec-1",
            "update_token": "update-1",
            "command": "echo hello",
            "command_digest": "sha256:" + "a" * 64,
            "workdir": None,
            "host": "gateway",
            "placement": None,
            "profiling": None,
        }

    def fake_best_effort(_endpoint: str, path: str, payload: dict[str, Any]) -> None:
        posts.append((path, payload))

    def fake_spawn(
        command: str,
        cwd: str | None,
        *,
        cgroup_path: str | None = None,
        affinity_cpus: set[int] | None = None,
    ) -> _FakeChild:
        assert command == "echo hello"
        assert cwd is None
        assert cgroup_path is None
        assert affinity_cpus is None
        return _FakeChild()

    monkeypatch.setattr(launcher, "_post_json", fake_post_json)
    monkeypatch.setattr(launcher, "_post_json_best_effort", fake_best_effort)
    monkeypatch.setattr(launcher, "_spawn_shell", fake_spawn)
    monkeypatch.setattr(launcher, "_install_signal_forwarders", lambda _child: None)
    monkeypatch.setattr(launcher, "_read_pid_starttime_ticks", lambda _pid: 99)
    monkeypatch.setattr(launcher, "_pid_namespace_inode", lambda _pid: 123)

    assert launcher.run_execution("http://sidecar", "exec-1", "token-1") == 7
    assert posts[0] == (
        "/v2/executions/claim",
        {"execution_id": "exec-1", "token": "token-1", "launcher_pid": posts[0][1]["launcher_pid"]},
    )
    assert posts[1] == (
        "/v2/executions/exec-1/started",
        {
            "update_token": "update-1",
            "launcher_pid": posts[1][1]["launcher_pid"],
            "child_pid": 4242,
            "process_starttime_ticks": 99,
            "cgroup_path": None,
            "pid_namespace_inode": 123,
            "container_id": None,
        },
    )
    assert posts[2] == (
        "/v2/executions/exec-1/exited",
        {"update_token": "update-1", "exit_code": 7, "signal": None},
    )


def test_launcher_extracts_cpu_and_numa_placement() -> None:
    placement = {"cpu_set": "0-2,4", "numa_node": 1}

    assert launcher._extract_cpu_set(placement) == "0-2,4"
    assert launcher._extract_mems(placement) == "1"
    assert launcher._parse_cpu_list("0-2,4") == {0, 1, 2, 4}


def test_launcher_prepares_cgroup_with_cpuset_order(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(launcher, "_supports_posix_controls", lambda: True)
    monkeypatch.setenv("CLAW_CGROUP_ROOT", str(tmp_path))

    cgroup_path = launcher._prepare_cgroup(
        "exec:1",
        "2-3",
        "0",
        {"enable_cgroup": True},
    )

    assert cgroup_path == str(tmp_path / "exec_1")
    assert (tmp_path / "exec_1" / "cpuset.mems").read_text(encoding="utf-8") == "0"
    assert (tmp_path / "exec_1" / "cpuset.cpus").read_text(encoding="utf-8") == "2-3"


def test_launcher_can_require_cgroup(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(launcher, "_supports_posix_controls", lambda: True)
    monkeypatch.setenv("CLAW_CGROUP_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAW_CGROUP_REQUIRED", "1")
    monkeypatch.delenv("CLAW_CGROUP_PATH", raising=False)
    monkeypatch.setattr(launcher, "_write_file", lambda _path, _value: (_ for _ in ()).throw(OSError("blocked")))

    with pytest.raises(RuntimeError, match="cgroup_unavailable"):
        launcher._prepare_cgroup(
            "exec:1",
            "0",
            None,
            {"enable_cgroup": True},
        )


def test_launcher_required_cgroup_overrides_profiling_disable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(launcher, "_supports_posix_controls", lambda: True)
    monkeypatch.setenv("CLAW_CGROUP_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAW_CGROUP_REQUIRED", "1")
    monkeypatch.delenv("CLAW_CGROUP_PATH", raising=False)

    cgroup_path = launcher._prepare_cgroup(
        "exec:1",
        None,
        None,
        {"enable_cgroup": False},
    )

    assert cgroup_path == str(tmp_path / "exec_1")


def test_launcher_required_cgroup_fails_without_posix(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "_supports_posix_controls", lambda: False)
    monkeypatch.setenv("CLAW_CGROUP_REQUIRED", "1")

    with pytest.raises(RuntimeError, match="posix_controls_unsupported"):
        launcher._prepare_cgroup(
            "exec:1",
            None,
            None,
            {"enable_cgroup": True},
        )


def test_launcher_required_cgroup_verifies_child_membership(monkeypatch, tmp_path) -> None:
    cgroup_path = tmp_path / "exec-1"
    cgroup_path.mkdir()
    (cgroup_path / "cgroup.procs").write_text("123\n", encoding="utf-8")
    monkeypatch.setenv("CLAW_CGROUP_REQUIRED", "1")

    with pytest.raises(RuntimeError, match="cgroup_join_missing"):
        launcher._verify_child_cgroup(456, str(cgroup_path))

    (cgroup_path / "cgroup.procs").write_text("456\n", encoding="utf-8")
    launcher._verify_child_cgroup(456, str(cgroup_path))


def test_launcher_required_cgroup_reports_parent_join_failure(monkeypatch, tmp_path) -> None:
    cgroup_path = tmp_path / "exec-1"
    cgroup_path.mkdir()
    monkeypatch.setenv("CLAW_CGROUP_REQUIRED", "1")
    monkeypatch.setattr(launcher, "_write_file", lambda _path, _value: (_ for _ in ()).throw(OSError("blocked")))

    with pytest.raises(RuntimeError, match="cgroup_join_failed"):
        launcher._join_child_cgroup(456, str(cgroup_path))


def test_launcher_cgroup_join_failure_falls_back_when_not_required(monkeypatch, tmp_path) -> None:
    cgroup_path = tmp_path / "exec-1"
    cgroup_path.mkdir()
    monkeypatch.delenv("CLAW_CGROUP_REQUIRED", raising=False)
    monkeypatch.setattr(launcher, "_write_file", lambda _path, _value: (_ for _ in ()).throw(OSError("blocked")))

    assert launcher._join_child_cgroup(456, str(cgroup_path)) is False


def test_launcher_passes_placement_to_spawn(monkeypatch, tmp_path) -> None:
    posts: list[tuple[str, dict[str, Any]]] = []

    def fake_post_json(_endpoint: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        posts.append((path, payload))
        return {
            "execution_id": "exec-1",
            "update_token": "update-1",
            "command": "echo hello",
            "command_digest": "sha256:" + "a" * 64,
            "workdir": None,
            "host": "gateway",
            "placement": {"cpu_set": "1,3", "numa_node": 0},
            "profiling": {"enable_cgroup": True, "enable_affinity": True},
        }

    def fake_best_effort(_endpoint: str, path: str, payload: dict[str, Any]) -> None:
        posts.append((path, payload))

    def fake_spawn(
        _command: str,
        _cwd: str | None,
        *,
        cgroup_path: str | None = None,
        affinity_cpus: set[int] | None = None,
    ) -> _FakeChild:
        assert cgroup_path == str(tmp_path / "exec-1")
        assert affinity_cpus == {1, 3}
        return _FakeChild()

    monkeypatch.setattr(launcher, "_supports_posix_controls", lambda: True)
    monkeypatch.setenv("CLAW_CGROUP_ROOT", str(tmp_path))
    monkeypatch.setattr(launcher, "_post_json", fake_post_json)
    monkeypatch.setattr(launcher, "_post_json_best_effort", fake_best_effort)
    monkeypatch.setattr(launcher, "_spawn_shell", fake_spawn)
    monkeypatch.setattr(launcher, "_install_signal_forwarders", lambda _child: None)
    monkeypatch.setattr(launcher, "_read_pid_starttime_ticks", lambda _pid: 99)
    monkeypatch.setattr(launcher, "_pid_namespace_inode", lambda _pid: 123)

    assert launcher.run_execution("http://sidecar", "exec-1", "token-1") == 7
    assert posts[1][1]["cgroup_path"] == str(tmp_path / "exec-1")


def test_launcher_accepts_dash_prefixed_token_with_equals(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_run(endpoint: str, execution_id: str, token: str) -> int:
        seen["endpoint"] = endpoint
        seen["execution_id"] = execution_id
        seen["token"] = token
        return 0

    monkeypatch.setattr(launcher, "run_execution", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "claw-launch",
            "run",
            "--endpoint",
            "http://sidecar",
            "--execution-id",
            "exec-1",
            "--token=-leading-token",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        launcher.main()

    assert exc.value.code == 0
    assert seen == {
        "endpoint": "http://sidecar",
        "execution_id": "exec-1",
        "token": "-leading-token",
    }
