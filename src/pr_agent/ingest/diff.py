"""Unified diff parsing and reviewability filtering."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

from unidiff import PatchedFile, PatchSet

from pr_agent.models import ChangedFile

_SKIP_GLOBS = ["*.lock", "package-lock.json", "*.min.js", "*_pb2.py", "*.generated.*"]
_SKIP_DIRS = {"vendor", "third_party", "node_modules"}
_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf", ".zip", ".gz",
    ".tar", ".whl", ".so", ".dll", ".dylib", ".exe", ".bin", ".pyc", ".woff", ".woff2",
}  # fmt: skip


def _strip_prefix(path: str | None) -> str | None:
    """`a/src/x.py` -> `src/x.py`; `/dev/null` -> None."""
    if not path or path == "/dev/null":
        return None
    return path[2:] if path.startswith(("a/", "b/")) else path


def _status(pf: PatchedFile) -> str:
    if pf.is_added_file:
        return "added"
    if pf.is_removed_file:
        return "deleted"
    if pf.is_rename:
        return "renamed"
    return "modified"


def parse_diff(diff_text: str) -> list[ChangedFile]:
    """One ChangedFile per file in the diff, with head line numbers of added lines."""
    files = []
    for pf in PatchSet(diff_text):
        status = _status(pf)
        added = [ln.target_line_no for h in pf for ln in h if ln.is_added and ln.target_line_no]
        files.append(
            ChangedFile(
                path=pf.path,
                status=status,  # type: ignore[arg-type]
                old_path=_strip_prefix(pf.source_file) if status == "renamed" else None,
                added_lines=added,
                patch=str(pf),
            )
        )
    return files


def is_reviewable(path: str) -> bool:
    """False for lock files, binaries, minified, vendored and generated files."""
    p = PurePosixPath(path)
    if _SKIP_DIRS & set(p.parts[:-1]):
        return False
    if p.suffix.lower() in _BINARY_EXT:
        return False
    return not any(fnmatch(p.name, g) for g in _SKIP_GLOBS)
