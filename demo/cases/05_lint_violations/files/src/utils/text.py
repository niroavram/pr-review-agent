from typing import Optional
import re
import os


def slugify(text: str, sep: Optional[str] = None) -> str:
    """Lowercase `text` and join its words with `sep` (default "-")."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return (sep or "-").join(words)
