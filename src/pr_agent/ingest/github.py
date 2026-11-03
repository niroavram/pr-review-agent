"""Build a PRContext from a GitHub pull request URL (`--pr <url>` mode).

PR metadata comes from the REST API; code comes from a cached partial clone of the repo.
The token is only ever sent as an HTTP header. It is never logged, never put in a git
command line and never included in an exception message. Cloning private repos relies on
the user's git credential helper.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from pr_agent.gitutil import git
from pr_agent.ingest.diff import parse_diff
from pr_agent.models import PRContext

API = "https://api.github.com"
_PR_URL = re.compile(
    r"https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)"
    r"/(?P<repo>[A-Za-z0-9._-]+)/pull/(?P<number>[1-9][0-9]*)/?"
)


class GitHubError(RuntimeError):
    """The PR could not be loaded. Messages never contain the token."""


@dataclass(frozen=True)
class PullRef:
    """`https://github.com/<owner>/<repo>/pull/<number>`, parsed."""

    owner: str
    repo: str
    number: int

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class PullInfo:
    """The fields we read from the GitHub pull request payload."""

    title: str
    body: str
    base_sha: str
    base_ref: str
    head_sha: str
    head_ref: str


def parse_pr_url(url: str) -> PullRef:
    """Parse a GitHub PR URL; anything else (other hosts, paths, `..`) raises ValueError."""
    match = _PR_URL.fullmatch(url.strip())
    if not match or match["repo"] in {".", ".."}:
        raise ValueError(f"not a GitHub pull request URL: {url!r}")
    return PullRef(match["owner"], match["repo"], int(match["number"]))


def api_headers(token: str | None) -> dict[str, str]:
    """API headers; Authorization only when a token is given."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_pull(ref: PullRef, token: str | None, client: httpx.Client) -> PullInfo:
    """GET /repos/<owner>/<repo>/pulls/<n> and keep title, body, base and head."""
    url = f"{API}/repos/{ref.full_name}/pulls/{ref.number}"
    try:
        resp = client.get(url, headers=api_headers(token))
    except httpx.HTTPError as e:
        # Only the exception type: its text could include request details.
        raise GitHubError(f"GitHub API request failed for {url}: {type(e).__name__}") from None
    if resp.status_code != 200:
        raise GitHubError(f"GitHub API returned {resp.status_code} for {url}")
    data: dict[str, Any] = resp.json()
    try:
        return PullInfo(
            title=data.get("title") or "",
            body=data.get("body") or "",
            base_sha=data["base"]["sha"],
            base_ref=data["base"].get("ref", ""),
            head_sha=data["head"]["sha"],
            head_ref=data["head"].get("ref", ""),
        )
    except (KeyError, TypeError) as e:
        raise GitHubError(f"unexpected GitHub API response for {url}: missing {e}") from None


def sync_repo(ref: PullRef, work_dir: Path, base_sha: str, clone_url: str | None) -> Path:
    """Clone (blob-less) or reuse `work_dir/repos/<owner>__<repo>`, then fetch base and PR head."""
    url = clone_url or f"https://github.com/{ref.full_name}.git"
    repo = work_dir / "repos" / f"{ref.owner}__{ref.repo}"
    if (repo / ".git").exists():
        git(repo, "remote", "set-url", "origin", url)
    else:
        repo.parent.mkdir(parents=True, exist_ok=True)
        git(repo.parent, "clone", "-q", "--filter=blob:none", url, repo.name)
    git(repo, "fetch", "-q", "origin", base_sha, f"pull/{ref.number}/head")
    return repo


def load_github(
    url: str,
    work_dir: Path,
    *,
    token: str | None = None,
    client: httpx.Client | None = None,
    clone_url: str | None = None,
) -> PRContext:
    """PR semantics as in local mode: the diff runs from merge-base(base, head) to head.

    `token` defaults to $GITHUB_TOKEN. `client` and `clone_url` exist for tests (a
    MockTransport client and a local bare repo).
    """
    ref = parse_pr_url(url)
    token = token if token is not None else os.environ.get("GITHUB_TOKEN")
    if client is None:
        with httpx.Client(timeout=30) as own_client:
            pull = fetch_pull(ref, token, own_client)
    else:
        pull = fetch_pull(ref, token, client)

    repo = sync_repo(ref, Path(work_dir), pull.base_sha, clone_url)
    base_sha = git(repo, "merge-base", pull.base_sha, pull.head_sha).strip()
    diff = git(repo, "diff", base_sha, pull.head_sha)
    return PRContext(
        repo_path=str(repo.resolve()),
        repo_name=ref.full_name,
        pr_id=str(ref.number),
        base_sha=base_sha,
        head_sha=pull.head_sha,
        head_ref=pull.head_ref,
        title=pull.title,
        description=pull.body,
        files=parse_diff(diff),
        diff=diff,
        mode="github",
    )
