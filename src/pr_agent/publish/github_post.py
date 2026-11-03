"""Post the review to the GitHub PR as one review comment (event COMMENT, never APPROVE)."""

from __future__ import annotations

from typing import Any

import httpx

from pr_agent.ingest.github import API, GitHubError, api_headers
from pr_agent.models import PRContext


def post_review(
    ctx: PRContext, review_md: str, token: str, client: httpx.Client | None = None
) -> dict[str, Any]:
    """POST /repos/<owner>/<repo>/pulls/<n>/reviews with the markdown body; returns the JSON.

    The event is always "COMMENT": the agent can never approve or request changes.
    Errors name the URL and status only, never the token.
    """
    if ctx.mode != "github":
        raise GitHubError("post_review needs a PR loaded from GitHub")
    url = f"{API}/repos/{ctx.repo_name}/pulls/{ctx.pr_id}/reviews"
    payload = {"body": review_md, "event": "COMMENT"}
    try:
        if client is None:
            with httpx.Client(timeout=30) as own_client:
                resp = own_client.post(url, headers=api_headers(token), json=payload)
        else:
            resp = client.post(url, headers=api_headers(token), json=payload)
    except httpx.HTTPError as e:
        raise GitHubError(f"GitHub API request failed for {url}: {type(e).__name__}") from None
    if resp.status_code not in (200, 201):
        raise GitHubError(f"GitHub API returned {resp.status_code} for {url}")
    result: dict[str, Any] = resp.json()
    return result
