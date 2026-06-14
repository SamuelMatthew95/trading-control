"""Tests for the GitOps auto-PR publisher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import settings
from api.constants import FieldName
from api.services import gitops_publisher
from api.services.gitops_publisher import GitOpsPublisher

pytestmark = pytest.mark.asyncio


def _artifact() -> dict:
    # An allowlisted, in-bounds change — open_parameter_pr validates against
    # PARAM_BOUNDS before any network call.
    return {
        FieldName.PARAMETER: "SIGNAL_CONFIDENCE_MIN_GATE",
        FieldName.PREVIOUS_VALUE: 0.65,
        FieldName.PROPOSED_VALUE: 0.50,
        FieldName.REASON: "too many momentum signals gated",
        FieldName.TRACE_ID: "t-1",
    }


async def test_dry_run_when_not_configured(monkeypatch):
    """No token → dry-run no-op, no network."""
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)
    result = await GitOpsPublisher().open_parameter_pr(_artifact())
    assert result[FieldName.STATUS] == "dry_run"


async def test_dry_run_when_disabled(monkeypatch):
    """Flag off → dry-run even with a token."""
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", False)
    result = await GitOpsPublisher().open_parameter_pr(_artifact())
    assert result[FieldName.STATUS] == "dry_run"


def _mock_github_client(*, existing_overrides: str | None = None):
    """An httpx.AsyncClient stub covering the 5 calls open_parameter_pr makes:
    GET base ref, GET overrides file, POST branch, PUT file, POST PR."""
    client = MagicMock()

    ref_resp = MagicMock(status_code=200)
    ref_resp.json.return_value = {"object": {"sha": "basesha"}}
    if existing_overrides is None:
        contents_resp = MagicMock(status_code=404)
    else:
        import base64

        contents_resp = MagicMock(status_code=200)
        contents_resp.raise_for_status = MagicMock()
        contents_resp.json.return_value = {
            "content": base64.b64encode(existing_overrides.encode()).decode(),
            "sha": "filesha",
        }
    client.get = AsyncMock(side_effect=[ref_resp, contents_resp])

    branch_resp = MagicMock()
    branch_resp.raise_for_status = MagicMock()
    put_resp = MagicMock()
    put_resp.raise_for_status = MagicMock()
    pr_resp = MagicMock()
    pr_resp.raise_for_status = MagicMock()
    pr_resp.json.return_value = {"html_url": "https://github.com/o/r/pull/7"}

    client.post = AsyncMock(side_effect=[branch_resp, pr_resp])
    client.put = AsyncMock(return_value=put_resp)
    return client


class _ClientCM:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *a):
        return False


async def test_opens_pr_when_configured(monkeypatch):
    """With token + repo + flag, it edits the validated overrides file and opens a PR."""
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)

    client = _mock_github_client()
    with patch.object(gitops_publisher.httpx, "AsyncClient", lambda **_: _ClientCM(client)):
        result = await GitOpsPublisher().open_parameter_pr(_artifact())

    assert result[FieldName.STATUS] == "opened"
    assert result[FieldName.PR_URL] == "https://github.com/o/r/pull/7"
    # branch create + PR open = 2 POSTs; overrides write = 1 PUT.
    assert client.post.await_count == 2
    assert client.put.await_count == 1
    # The committed file is THE validated overrides document, never source code.
    put_path = client.put.await_args.args[0]
    assert put_path == "/repos/o/r/contents/config/param_overrides.json"
    # The committed body is the read-modify-write result of apply_param_override.
    import base64
    import json

    committed = json.loads(base64.b64decode(client.put.await_args.kwargs["json"]["content"]))
    assert committed == {"SIGNAL_CONFIDENCE_MIN_GATE": 0.50}


async def test_updating_existing_overrides_preserves_other_entries(monkeypatch):
    """Read-modify-write: existing overrides survive, the file sha rides the PUT."""
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)

    client = _mock_github_client(existing_overrides='{"STOP_LOSS_PCT": 0.05}\n')
    with patch.object(gitops_publisher.httpx, "AsyncClient", lambda **_: _ClientCM(client)):
        result = await GitOpsPublisher().open_parameter_pr(_artifact())

    assert result[FieldName.STATUS] == "opened"
    import base64
    import json

    put_json = client.put.await_args.kwargs["json"]
    assert put_json["sha"] == "filesha"  # contents API requires it for updates
    committed = json.loads(base64.b64decode(put_json["content"]))
    assert committed == {"SIGNAL_CONFIDENCE_MIN_GATE": 0.50, "STOP_LOSS_PCT": 0.05}


async def test_rejects_off_allowlist_or_out_of_bounds_before_any_network(monkeypatch):
    """Safe-bounds gate fires before any branch/PR exists — no orphan branches."""
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)

    client = MagicMock()
    with patch.object(gitops_publisher.httpx, "AsyncClient", lambda **_: _ClientCM(client)):
        off_list = await GitOpsPublisher().open_parameter_pr(
            {FieldName.PARAMETER: "REASONING_COOLDOWN_SECONDS", FieldName.PROPOSED_VALUE: 90}
        )
        out_of_bounds = await GitOpsPublisher().open_parameter_pr(
            {FieldName.PARAMETER: "MAX_RISK_PER_TRADE_PCT", FieldName.PROPOSED_VALUE: 5.0}
        )

    assert off_list[FieldName.STATUS] == "rejected"
    assert out_of_bounds[FieldName.STATUS] == "rejected"
    assert "bounds" in out_of_bounds[FieldName.REASON]


async def test_missing_base_ref_returns_error(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)

    client = MagicMock()
    client.get = AsyncMock(return_value=MagicMock(status_code=404))

    class _CM:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *a):
            return False

    with patch.object(gitops_publisher.httpx, "AsyncClient", lambda **_: _CM()):
        result = await GitOpsPublisher().open_parameter_pr(_artifact())
    assert result[FieldName.STATUS] == "error"


async def test_open_feature_issue_dry_run_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "")
    result = await GitOpsPublisher().open_feature_issue("new tool", "please add X")
    assert result[FieldName.STATUS] == "dry_run"


async def test_open_feature_issue_creates_issue(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)

    issue_resp = MagicMock()
    issue_resp.raise_for_status = MagicMock()
    issue_resp.json.return_value = {"html_url": "https://github.com/o/r/issues/3"}
    client = MagicMock()
    client.post = AsyncMock(return_value=issue_resp)

    class _CM:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *a):
            return False

    with patch.object(gitops_publisher.httpx, "AsyncClient", lambda **_: _CM()):
        result = await GitOpsPublisher().open_feature_issue("new tool", "add X", labels=["auto"])

    assert result[FieldName.STATUS] == "opened"
    assert result[FieldName.PR_URL] == "https://github.com/o/r/issues/3"
    assert client.post.await_args.args[0] == "/repos/o/r/issues"


async def test_autopr_refuses_to_write_outside_overrides_file(monkeypatch):
    """Structural guarantee: _put_file rejects any path but the overrides document."""
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    pub = GitOpsPublisher()
    client = MagicMock()
    client.put = AsyncMock()
    with pytest.raises(ValueError, match="outside"):
        await pub._put_file(client, "api/constants.py", "{}", "br", "msg")
    client.put.assert_not_awaited()


# ---------------------------------------------------------------------------
# Error observability + access verification (the now-live path)
# ---------------------------------------------------------------------------


async def test_open_parameter_pr_surfaces_github_error_detail(monkeypatch):
    """A GitHub failure (e.g. token lacks PR scope) reports the status + message
    instead of an opaque 'github_api_error', so the operator can diagnose it."""
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)

    client = _mock_github_client()
    err_resp = MagicMock(status_code=403)
    err_resp.json.return_value = {"message": "Resource not accessible by personal access token"}

    def _raise_403():
        raise gitops_publisher.httpx.HTTPStatusError("403", request=MagicMock(), response=err_resp)

    branch_resp = MagicMock()
    branch_resp.raise_for_status = MagicMock()
    pr_resp = MagicMock()
    pr_resp.raise_for_status = _raise_403
    client.post = AsyncMock(side_effect=[branch_resp, pr_resp])

    with patch.object(gitops_publisher.httpx, "AsyncClient", lambda **_: _ClientCM(client)):
        result = await GitOpsPublisher().open_parameter_pr(_artifact())

    assert result[FieldName.STATUS] == "error"
    assert "github_403" in result[FieldName.REASON]
    assert "personal access token" in result[FieldName.REASON]


async def test_verify_access_disabled_when_no_token(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)
    result = await GitOpsPublisher().verify_access()
    assert result[FieldName.STATUS] == "disabled"
    assert result["ready"] is False
    assert "GITHUB_TOKEN" in result[FieldName.REASON]


async def test_verify_access_ok(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)
    repo_resp = MagicMock(status_code=200)
    ref_resp = MagicMock(status_code=200)
    ref_resp.json.return_value = {"object": {"sha": "s"}}
    client = MagicMock()
    client.get = AsyncMock(side_effect=[repo_resp, ref_resp])
    with patch.object(gitops_publisher.httpx, "AsyncClient", lambda **_: _ClientCM(client)):
        result = await GitOpsPublisher().verify_access()
    assert result[FieldName.STATUS] == "ok"
    assert result["ready"] is True
    assert result["repo"] == "o/r"


async def test_verify_access_reports_repo_error(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "badtok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)
    repo_resp = MagicMock(status_code=401)
    repo_resp.json.return_value = {"message": "Bad credentials"}
    client = MagicMock()
    client.get = AsyncMock(side_effect=[repo_resp])
    with patch.object(gitops_publisher.httpx, "AsyncClient", lambda **_: _ClientCM(client)):
        result = await GitOpsPublisher().verify_access()
    assert result[FieldName.STATUS] == "error"
    assert result["ready"] is False
    assert result["http_status"] == 401
    assert "Bad credentials" in result[FieldName.REASON]
