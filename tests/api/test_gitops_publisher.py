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
    return {
        FieldName.PARAMETER: "REASONING_COOLDOWN_SECONDS",
        FieldName.PREVIOUS_VALUE: 60,
        FieldName.PROPOSED_VALUE: 90,
        FieldName.REASON: "too many calls",
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


def _mock_github_client():
    """An httpx.AsyncClient stub covering the 4 calls open_parameter_pr makes."""
    client = MagicMock()

    ref_resp = MagicMock(status_code=200)
    ref_resp.json.return_value = {"object": {"sha": "basesha"}}
    client.get = AsyncMock(return_value=ref_resp)

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


async def test_opens_pr_when_configured(monkeypatch):
    """With token + repo + flag, it creates branch, writes config file, opens PR."""
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    monkeypatch.setattr(settings, "GITHUB_AUTOPR_ENABLED", True)

    client = _mock_github_client()

    class _CM:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *a):
            return False

    with patch.object(gitops_publisher.httpx, "AsyncClient", lambda **_: _CM()):
        result = await GitOpsPublisher().open_parameter_pr(_artifact())

    assert result[FieldName.STATUS] == "opened"
    assert result[FieldName.PR_URL] == "https://github.com/o/r/pull/7"
    # branch create + PR open = 2 POSTs; config file write = 1 PUT.
    assert client.post.await_count == 2
    assert client.put.await_count == 1
    # The committed file is a config override, never source code.
    put_path = client.put.await_args.args[0]
    assert put_path.startswith("/repos/o/r/contents/config/parameter_overrides/")


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


async def test_autopr_refuses_to_write_outside_config_dir(monkeypatch):
    """Structural guarantee: _put_file rejects any path outside the overrides dir."""
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "tok")
    monkeypatch.setattr(settings, "GITHUB_REPO", "o/r")
    pub = GitOpsPublisher()
    client = MagicMock()
    client.put = AsyncMock()
    with pytest.raises(ValueError, match="outside"):
        await pub._put_file(client, "api/constants.py", {"x": 1}, "br", "msg")
    client.put.assert_not_awaited()
