import json

import httpx
import pytest

from pr_agent.ingest.github import GitHubError
from pr_agent.models import PRContext
from pr_agent.publish.github_post import post_review

TOKEN = "ghp_s3cret-token-value"
CTX = PRContext(
    repo_path=".", repo_name="acme/shop", pr_id="7", base_sha="a", head_sha="b", mode="github"
)


def client_returning(status: int, seen: list[httpx.Request]) -> httpx.Client:
    """A MockTransport client that records requests and answers with `status`."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"id": 1})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_post_review_posts_one_comment_review() -> None:
    seen: list[httpx.Request] = []
    assert post_review(CTX, "## Review\nF1", TOKEN, client=client_returning(200, seen)) == {"id": 1}
    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == "https://api.github.com/repos/acme/shop/pulls/7/reviews"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert json.loads(request.content) == {"body": "## Review\nF1", "event": "COMMENT"}


def test_post_review_error_hides_token() -> None:
    with pytest.raises(GitHubError) as err:
        post_review(CTX, "x", TOKEN, client=client_returning(422, []))
    assert "422" in str(err.value) and TOKEN not in str(err.value)


def test_post_review_needs_a_github_pr() -> None:
    seen: list[httpx.Request] = []
    local = CTX.model_copy(update={"mode": "local"})
    with pytest.raises(GitHubError):
        post_review(local, "x", TOKEN, client=client_returning(200, seen))
    assert seen == []
