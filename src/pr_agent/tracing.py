"""Secret redaction (for traces AND review output) and LangSmith run config."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\blsv2_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
]
# key = "value" where key looks secret-ish; value redacted if long and high-entropy
_ASSIGN = re.compile(
    r"""(?i)((?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)\w*"""
    r"""\s*[:=]\s*['"])([^'"\s]{8,})(['"])"""
)


def _entropy(s: str) -> float:
    counts = Counter(s)
    return -sum(c / len(s) * math.log2(c / len(s)) for c in counts.values())


def redact_text(text: str) -> str:
    for p in _PATTERNS:
        text = p.sub(REDACTED, text)

    def _mask(m: re.Match[str]) -> str:
        value = m.group(2)
        return m.group(1) + (REDACTED if _entropy(value) >= 3.0 else value) + m.group(3)

    return _ASSIGN.sub(_mask, text)


def redact(obj: Any) -> Any:
    """Recursively redact strings in dicts/lists (LangSmith hide_inputs/hide_outputs hook)."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [redact(v) for v in obj]
    return obj
