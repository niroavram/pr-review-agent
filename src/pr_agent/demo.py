"""Builds the throwaway demo git repo: `main` = demo/base, one branch per seeded case.

Case layout: demo/cases/NN_slug/{pr.json, expected.json, files/<overlay>}. Files ending in
`.tmpl` are rendered at build time, so no secret-looking literal is ever committed here.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from pr_agent.gitutil import git

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo"
_IDENT = ["-c", "user.name=pr-agent-demo", "-c", "user.email=demo@example.invalid"]


def demo_secret(case: str) -> str:
    """Deterministic, generic high-entropy hex value. Assembled, never stored."""
    seed = "-".join(["pr", "agent", "demo", case])
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def render(text: str, case: str) -> str:
    return text.replace("{{SECRET_HEX}}", demo_secret(case))


def list_cases() -> list[Path]:
    return sorted(p for p in (DEMO_DIR / "cases").iterdir() if (p / "pr.json").exists())


def load_case(case_dir: Path) -> dict:
    meta = json.loads((case_dir / "pr.json").read_text())
    expected_file = case_dir / "expected.json"
    meta["expected"] = json.loads(expected_file.read_text()) if expected_file.exists() else {}
    meta["case"] = case_dir.name
    return meta


def _commit(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, *_IDENT, "commit", "-q", "--allow-empty", "-m", message)


def build(out: Path) -> Path:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(DEMO_DIR / "base", out)
    git(out, "init", "-q", "-b", "main")
    _commit(out, "Initial demo shop")
    for case_dir in list_cases():
        meta = load_case(case_dir)
        git(out, "checkout", "-q", "-b", meta["branch"], "main")
        files = case_dir / "files"
        for src in sorted(p for p in files.rglob("*") if p.is_file()) if files.exists() else []:
            rel = src.relative_to(files)
            if src.suffix == ".tmpl":
                rel = rel.with_suffix("")
                content = render(src.read_text(), case_dir.name)
            else:
                content = src.read_text()
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_text(content)
        for rel in meta.get("delete", []):
            (out / rel).unlink(missing_ok=True)
        _commit(out, f"{meta['title']}\n\n{meta.get('description', '')}")
        git(out, "checkout", "-q", "main")
    return out
