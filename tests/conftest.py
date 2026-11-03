from __future__ import annotations

from pathlib import Path

import pytest

from pr_agent.demo import build


@pytest.fixture(scope="session")
def demo_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Built demo git repo with main + one branch per seeded case."""
    return build(tmp_path_factory.mktemp("demo") / "repo")
