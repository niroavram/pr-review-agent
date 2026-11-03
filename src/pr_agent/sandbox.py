"""Where analyzers and tests execute. Docker (isolated) or a local temp dir (fallback)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DEFAULT_IMAGE = "pr-agent-sandbox:0.1"
DOCKERFILE = Path(__file__).with_name("sandbox.Dockerfile")
CONTAINER_WORKDIR = "/work"  # where DockerSandbox mounts the checkout
LOCAL_BANNER = (
    "⚠️ Sandbox: Docker unavailable, running in a local temp dir (not isolated). "
    "Tests run only for --local reviews."
)
DOCKER_PROBE_TIMEOUT = 15
IMAGE_BUILD_TIMEOUT = 900


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class Sandbox(Protocol):
    mode: str  # "docker" | "local"
    isolated: bool  # True only when untrusted code is safe to execute

    def run(self, cmd: list[str], workdir: Path, timeout: int = 120) -> ExecResult: ...

    def python(self) -> list[str]:
        """The interpreter command for `python -m <tool>` inside this sandbox."""
        ...


class LocalSandbox:
    """Runs commands as subprocesses in a temp checkout. NOT isolated: no network/FS limits."""

    mode = "local"
    isolated = False

    def run(self, cmd: list[str], workdir: Path, timeout: int = 120) -> ExecResult:
        try:
            p = subprocess.run(
                cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout, check=False
            )
            return ExecResult(p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired as e:
            return ExecResult(-1, _s(e.stdout), _s(e.stderr), timed_out=True)
        except FileNotFoundError as e:
            return ExecResult(127, "", str(e))

    def python(self) -> list[str]:
        """This process's interpreter: its venv has ruff, bandit, semgrep and pytest."""
        return [sys.executable]


class DockerSandbox:
    """One throwaway container per command: no network, capped resources, non-root, no caps."""

    mode = "docker"
    isolated = True

    def __init__(self, image: str = DEFAULT_IMAGE) -> None:
        self.image = image

    def docker_cmd(self, cmd: list[str], workdir: Path, name: str) -> list[str]:
        """The full `docker run` invocation for `cmd` with `workdir` mounted at /work."""
        return [
            "docker", "run", "--rm",
            "--network", "none",
            "--cpus", "2", "--memory", "2g", "--pids-limit", "256",
            "--read-only", "--tmpfs", "/tmp",
            "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
            "--user", "1000:1000",
            "-e", "HOME=/tmp",  # the root fs is read-only; tools may write caches under $HOME
            "-v", f"{workdir.resolve()}:{CONTAINER_WORKDIR}", "-w", CONTAINER_WORKDIR,
            "--name", name,
            self.image, *cmd,
        ]  # fmt: skip

    def run(self, cmd: list[str], workdir: Path, timeout: int = 120) -> ExecResult:
        """Run `cmd` in a fresh container. On timeout the container is killed, not just the CLI."""
        name = f"pr-agent-{uuid.uuid4().hex[:12]}"
        try:
            p = subprocess.run(
                self.docker_cmd(cmd, workdir, name),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return ExecResult(p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired as e:
            # Killing the docker client leaves the container running; stop it explicitly.
            subprocess.run(["docker", "kill", name], capture_output=True, check=False)
            return ExecResult(-1, _s(e.stdout), _s(e.stderr), timed_out=True)
        except FileNotFoundError as e:
            return ExecResult(127, "", str(e))

    def python(self) -> list[str]:
        """The image's interpreter, on PATH."""
        return ["python"]


def _docker(*args: str, timeout: int, stdin: str | None = None) -> bool:
    """Run a docker CLI command; True on exit 0. A missing CLI or a hang counts as failure."""
    try:
        p = subprocess.run(
            ["docker", *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


def docker_available() -> bool:
    """True when the docker CLI exists and its daemon answers."""
    return _docker("info", timeout=DOCKER_PROBE_TIMEOUT)


def ensure_image(image: str = DEFAULT_IMAGE) -> bool:
    """Make sure the sandbox image exists, building it from sandbox.Dockerfile if needed.

    The Dockerfile is sent on stdin with no build context: it needs no local files.
    """
    if _docker("image", "inspect", image, timeout=DOCKER_PROBE_TIMEOUT):
        return True
    return _docker(
        "build", "-t", image, "-", timeout=IMAGE_BUILD_TIMEOUT, stdin=DOCKERFILE.read_text()
    )


def get_sandbox(settings: Any) -> tuple[Sandbox, list[str]]:
    """Pick the sandbox from settings.sandbox ("auto" | "docker" | "local"). Returns (sandbox,
    banners). "docker" raises RuntimeError when Docker cannot be used; "auto" falls back."""
    mode = settings.sandbox
    if mode == "local":
        return LocalSandbox(), [LOCAL_BANNER]
    if mode not in ("auto", "docker"):
        raise ValueError(f"unknown sandbox mode {mode!r} (expected auto, docker or local)")
    if docker_available() and ensure_image():
        return DockerSandbox(), []
    if mode == "docker":
        raise RuntimeError(
            f"sandbox=docker, but the Docker daemon or image {DEFAULT_IMAGE} is unavailable"
        )
    return LocalSandbox(), [LOCAL_BANNER]


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def _s(b: bytes | str | None) -> str:
    if b is None:
        return ""
    return b.decode(errors="replace") if isinstance(b, bytes) else b
