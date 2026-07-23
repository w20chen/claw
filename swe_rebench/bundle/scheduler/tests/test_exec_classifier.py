from __future__ import annotations

import pytest

from agent_scheduler.predictors.exec_classifier import classify_exec_tool_name, extract_exec_operation


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            'cd /testbed && timeout 120 python3 -m pytest tests/ -v '
            '2>&1 | grep -E "(PASSED|FAILED|ERROR)"',
            "exec-pytest",
        ),
        ("grep -r pattern .", "exec-grep"),
        ("python3 -m pytest tests/ -v", "exec-pytest"),
        ("pip install requests", "exec-pip"),
        ("git clone https://github.com/foo/bar.git", "exec-git"),
        ("find . -name '*.py' | xargs grep TODO", "exec-grep"),
        ("VAR=val grep pattern file", "exec-grep"),
        ("/usr/local/bin/custom-script arg1", "exec-custom-script"),
        ("$TOOL --flag", "exec"),
    ],
)
def test_classify_exec_tool_name_matches_agent_test_bench_representative_cases(
    command: str,
    expected: str,
) -> None:
    assert classify_exec_tool_name("exec", {"command": command}) == expected


def test_extract_exec_operation_prefers_existing_classified_tool_name() -> None:
    assert extract_exec_operation("exec-pytest", {"command": "grep pattern"}) == "pytest"
