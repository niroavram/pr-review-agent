from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from pr_agent.gitutil import git, rev_parse
from pr_agent.ingest.github import GitHubError, load_github, parse_pr_url
from pr_agent.ingest.local import load_local

URL = "https://github.com/acme/shop/pull/7"
API_URL = "https://api.github.com/repos/acme/shop/pulls/7"
TOKEN = "ghp_s3cret-token-value"
CASE = "case/01-sql-injection"


@pytest.fixture
def remote(demo_repo: Path, tmp_path: Path) -> Path:
    """A bare 'GitHub' remote: main is the base and refs/pull/7/head is the case 01 commit."""
    bare = tmp_path / "shop.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(demo_repo, "push", "-q", str(bare), "main:refs/heads/main")
    git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    git(demo_repo, "push", "-q", str(bare), f"{CASE}:refs/pull/7/head")
    return bare


def pull_json(demo_repo: Path, body: str | None = "Adds search.") -> dict[str, Any]:
    """The subset of GitHub's pull request payload that load_github reads."""
    return {
        "title": "Add order search",
        "body": body,
        "base": {"sha": rev_parse(demo_repo, "main"), "ref": "main"},
        "head": {"sha": rev_parse(demo_repo, CASE), "ref": "feature/search"},
    }


def mock_client(
    respond: Callable[[httpx.Request], httpx.Response], seen: list[httpx.Request]
) -> httpx.Client:
    """An httpx client whose requests are recorded and answered by `respond`."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_load_github_builds_context_from_api_and_clone(
    demo_repo: Path, remote: Path, tmp_path: Path
) -> None:
    seen: list[httpx.Request] = []
    client = mock_client(lambda r: httpx.Response(200, json=pull_json(demo_repo)), seen)
    work = tmp_path / "work"
    ctx = load_github(URL, work, token=TOKEN, client=client, clone_url=str(remote))

    [request] = seen
    assert str(request.url) == API_URL and request.method == "GET"
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"

    assert (ctx.mode, ctx.pr_id, ctx.repo_name) == ("github", "7", "acme/shop")
    assert (ctx.title, ctx.description, ctx.head_ref) == (
        "Add order search",
        "Adds search.",
        "feature/search",
    )
    assert ctx.base_sha == git(demo_repo, "merge-base", "main", CASE).strip()
    assert ctx.head_sha == rev_parse(demo_repo, CASE)
    local = load_local(demo_repo, "main", CASE)  # same PR, loaded from the source repo
    assert (ctx.diff, ctx.files) == (local.diff, local.files)
    assert "src/store/orders.py" in [f.path for f in ctx.files]
    assert Path(ctx.repo_path) == (work / "repos" / "acme__shop").resolve()

    # A second load reuses the cached clone (update path) and gives the same result.
    again = load_github(URL, work, token=TOKEN, client=client, clone_url=str(remote))
    assert again == ctx


def test_token_defaults_to_env_and_is_optional(
    demo_repo: Path, remote: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx.Request] = []
    client = mock_client(lambda r: httpx.Response(200, json=pull_json(demo_repo, None)), seen)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    ctx = load_github(URL, tmp_path, client=client, clone_url=str(remote))
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert ctx.description == ""  # GitHub sends null for an empty body

    monkeypatch.delenv("GITHUB_TOKEN")
    load_github(URL, tmp_path, client=client, clone_url=str(remote))
    assert "Authorization" not in seen[1].headers


@pytest.mark.parametrize(
    "respond",
    [
        lambda r: httpx.Response(404, json={"message": "Not Found"}),
        lambda r: httpx.Response(401, text=f"bad credentials {r.headers['Authorization']}"),
        lambda r: httpx.Response(200, json={"title": "no base or head"}),
    ],
)
def test_api_errors_never_contain_the_token(
    tmp_path: Path, respond: Callable[[httpx.Request], httpx.Response]
) -> None:
    client = mock_client(respond, [])
    with pytest.raises(GitHubError) as err:
        load_github(URL, tmp_path, token=TOKEN, client=client, clone_url="/nonexistent")
    assert TOKEN not in str(err.value) and TOKEN not in repr(err.value)


def test_transport_errors_never_contain_the_token(tmp_path: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed with {request.headers['Authorization']}")

    with pytest.raises(GitHubError) as err:
        load_github(URL, tmp_path, token=TOKEN, client=mock_client(boom, []))
    assert TOKEN not in str(err.value) and "ConnectError" in str(err.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/acme/shop/pull/7",
        "http://github.com/acme/shop/pull/7",
        "https://github.com/acme/shop/pulls/7",
        "https://github.com/acme/shop/pull/7/files",
        "https://github.com/acme/shop/pull/abc",
        "https://github.com/acme/shop/pull/0",
        "https://github.com/acme/../pull/7",
        "https://github.com/acme/shop/pull/7?x=1",
        "https://github.com.evil.com/acme/shop/pull/7",
        "github.com/acme/shop/pull/7",
    ],
)
def test_parse_pr_url_rejects_anything_else(url: str) -> None:
    with pytest.raises(ValueError):
        parse_pr_url(url)


def test_parse_pr_url_accepts_pr_urls() -> None:
    ref = parse_pr_url("https://github.com/my-org/repo.name_x/pull/123/")
    assert (ref.owner, ref.repo, ref.number, ref.full_name) == (
        "my-org",
        "repo.name_x",
        123,
        "my-org/repo.name_x",
    )
