"""Where analyzers and tests execute. Docker (isolated) or a local temp dir (fallback)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


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


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def _s(b: bytes | str | None) -> str:
    if b is None:
        return ""
    return b.decode(errors="replace") if isinstance(b, bytes) else b
