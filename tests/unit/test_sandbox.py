import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pr_agent import sandbox as sb
from pr_agent.sandbox import DockerSandbox, LocalSandbox, get_sandbox
from pr_agent.settings import Settings


class FakeRun:
    """Stands in for subprocess.run: records calls, answers per docker subcommand."""

    def __init__(self, returncodes: dict[str, int] | None = None, hang: bool = False) -> None:
        self.returncodes = returncodes or {}
        self.hang = hang
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        if self.hang and cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"], output=b"partial")
        code = self.returncodes.get(" ".join(cmd[1:3]), self.returncodes.get(cmd[1], 0))
        return subprocess.CompletedProcess(cmd, code, "out", "err")


def test_docker_command_is_locked_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRun()
    monkeypatch.setattr(sb.subprocess, "run", fake)
    res = DockerSandbox().run(["python", "-m", "pytest", "-q"], tmp_path, timeout=30)
    assert res.ok and res.stdout == "out"
    [cmd] = fake.calls
    name = cmd[cmd.index("--name") + 1]
    assert name.startswith("pr-agent-")
    assert cmd == [
        "docker", "run", "--rm",
        "--network", "none",
        "--cpus", "2", "--memory", "2g", "--pids-limit", "256",
        "--read-only", "--tmpfs", "/tmp",
        "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
        "--user", "1000:1000",
        "-e", "HOME=/tmp",
        "-v", f"{tmp_path.resolve()}:/work", "-w", "/work",
        "--name", name,
        "pr-agent-sandbox:0.1", "python", "-m", "pytest", "-q",
    ]  # fmt: skip


def test_timeout_kills_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRun(hang=True)
    monkeypatch.setattr(sb.subprocess, "run", fake)
    res = DockerSandbox().run(["sleep", "999"], tmp_path, timeout=1)
    assert res.timed_out and not res.ok and res.stdout == "partial"
    run_cmd, kill_cmd = fake.calls
    assert kill_cmd == ["docker", "kill", run_cmd[run_cmd.index("--name") + 1]]


def test_python_per_sandbox() -> None:
    assert LocalSandbox().python() == [sys.executable]
    assert DockerSandbox().python() == ["python"]
    assert DockerSandbox().isolated and not LocalSandbox().isolated


def test_auto_falls_back_to_local_when_docker_info_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRun({"info": 1})
    monkeypatch.setattr(sb.subprocess, "run", fake)
    sandbox, banners = get_sandbox(Settings(sandbox="auto"))
    assert isinstance(sandbox, LocalSandbox) and banners == [sb.LOCAL_BANNER]
    assert fake.calls == [["docker", "info"]]


def test_auto_falls_back_when_docker_cli_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(cmd: list[str], **_: Any) -> None:
        raise FileNotFoundError("docker")

    monkeypatch.setattr(sb.subprocess, "run", missing)
    sandbox, banners = get_sandbox(Settings(sandbox="auto"))
    assert isinstance(sandbox, LocalSandbox) and "Docker unavailable" in banners[0]


def test_auto_uses_docker_and_builds_missing_image(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRun({"image inspect": 1})
    monkeypatch.setattr(sb.subprocess, "run", fake)
    sandbox, banners = get_sandbox(Settings(sandbox="auto"))
    assert isinstance(sandbox, DockerSandbox) and banners == []
    assert [c[:3] for c in fake.calls] == [
        ["docker", "info"],
        ["docker", "image", "inspect"],
        ["docker", "build", "-t"],
    ]


def test_docker_mode_raises_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sb.subprocess, "run", FakeRun({"info": 1}))
    with pytest.raises(RuntimeError, match="sandbox=docker"):
        get_sandbox(Settings(sandbox="docker"))


def test_local_mode_never_probes_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRun()
    monkeypatch.setattr(sb.subprocess, "run", fake)
    sandbox, banners = get_sandbox(Settings(sandbox="local"))
    assert isinstance(sandbox, LocalSandbox) and banners == [sb.LOCAL_BANNER]
    assert fake.calls == []


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError, match="unknown sandbox mode"):
        get_sandbox(Settings(sandbox="vm"))


def test_dockerfile_pins_tools() -> None:
    text = sb.DOCKERFILE.read_text()
    for pin in ("ruff==", "bandit==", "semgrep==", "pytest==", "GITLEAKS_VERSION=", "TARGETARCH"):
        assert pin in text
    assert "USER 1000:1000" in text
