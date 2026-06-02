"""GitOps auto-PR publisher — turns a parameter-change proposal into a real PR.

When the learning loop approves a `PARAMETER_CHANGE`, the ProposalApplier emits
a `pr_request` artifact AND (via this module) opens a pull request that edits a
**config file** — never raw source code — so the change is version-controlled
and human-reviewed before it can affect anything.

The PR writes a JSON entry under ``config/parameter_overrides/`` describing the
proposed value + evidence. A human merges it; nothing in the live system changes
until then.

Safety: this only acts when ``GITHUB_AUTOPR_ENABLED`` is set AND a token + repo
are configured (``GITHUB_TOKEN`` lives in the Render env). With no token/repo —
local dev, tests, CI — every call is a **dry-run no-op** that touches no network.
All failures are swallowed: a GitOps hiccup must never break the trading loop.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from api.config import settings
from api.constants import PARAMETER_OVERRIDES_DIR, FieldName
from api.observability import log_structured

_GITHUB_API = "https://api.github.com"
_HTTP_TIMEOUT = 10.0


def _autopr_ready() -> bool:
    """True only when auto-PR is enabled and credentials are present."""
    return bool(settings.GITHUB_AUTOPR_ENABLED and settings.GITHUB_TOKEN and settings.GITHUB_REPO)


class GitOpsPublisher:
    """Opens config-only pull requests for approved parameter changes."""

    def __init__(self, token: str = "", repo: str = "", base_branch: str = "main") -> None:
        # Defaults pull from settings so callers can construct with no args.
        self.token = token or settings.GITHUB_TOKEN
        self.repo = repo or settings.GITHUB_REPO
        self.base_branch = base_branch or settings.GITHUB_AUTOPR_BASE_BRANCH

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def open_parameter_pr(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """Open a PR writing the parameter change to a config-override file.

        Returns a status dict — ``{status: dry_run}`` when not configured,
        ``{status: opened, pr_url: ...}`` on success, ``{status: error}`` on
        failure. Never raises.
        """
        if not _autopr_ready():
            return {FieldName.STATUS: "dry_run"}

        parameter = str(artifact.get(FieldName.PARAMETER) or "").strip()
        if not parameter:
            return {FieldName.STATUS: "error", FieldName.REASON: "missing_parameter"}

        short = uuid.uuid4().hex[:8]
        branch = f"auto/param-{parameter.lower()}-{short}"
        path = f"{PARAMETER_OVERRIDES_DIR}/{parameter}.{short}.json"
        proposed = artifact.get(FieldName.PROPOSED_VALUE)
        previous = artifact.get(FieldName.PREVIOUS_VALUE)
        reason = str(artifact.get(FieldName.REASON) or "")
        override = {
            FieldName.PARAMETER: parameter,
            FieldName.PREVIOUS_VALUE: previous,
            FieldName.PROPOSED_VALUE: proposed,
            FieldName.REASON: reason,
            FieldName.TRACE_ID: artifact.get(FieldName.TRACE_ID),
            FieldName.TIMESTAMP: datetime.now(timezone.utc).isoformat(),
        }
        title = f"[auto] param {parameter}: {previous} → {proposed}"
        body = (
            f"Automated parameter-change proposal from the learning loop.\n\n"
            f"- **parameter**: `{parameter}`\n"
            f"- **previous**: `{previous}`\n"
            f"- **proposed**: `{proposed}`\n"
            f"- **reason**: {reason}\n\n"
            f"This PR edits a config override only (no source code). "
            f"Review and merge to adopt."
        )

        try:
            async with httpx.AsyncClient(
                base_url=_GITHUB_API, headers=self._headers(), timeout=_HTTP_TIMEOUT
            ) as client:
                base_sha = await self._base_sha(client)
                if not base_sha:
                    return {FieldName.STATUS: "error", FieldName.REASON: "base_ref_not_found"}
                await self._create_branch(client, branch, base_sha)
                await self._put_file(client, path, override, branch, title)
                pr_url = await self._open_pr(client, branch, title, body)
        except Exception:
            log_structured("warning", "gitops_autopr_failed", parameter=parameter, exc_info=True)
            return {FieldName.STATUS: "error", FieldName.REASON: "github_api_error"}

        log_structured(
            "info", "gitops_autopr_opened", parameter=parameter, branch=branch, pr_url=pr_url
        )
        return {FieldName.STATUS: "opened", FieldName.PR_URL: pr_url, FieldName.BRANCH: branch}

    async def open_feature_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> dict[str, Any]:
        """File a GitHub issue for a proposal that needs CODE (a new tool, prompt,
        agent, or feature) — the system never edits code itself, it asks a human.

        Same safety contract as ``open_parameter_pr``: dry-run no-op when no
        token/repo, swallows all failures, never raises.
        """
        if not _autopr_ready():
            return {FieldName.STATUS: "dry_run"}
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        try:
            async with httpx.AsyncClient(
                base_url=_GITHUB_API, headers=self._headers(), timeout=_HTTP_TIMEOUT
            ) as client:
                resp = await client.post(f"/repos/{self.repo}/issues", json=payload)
                resp.raise_for_status()
                issue_url = str(resp.json().get("html_url") or "")
        except Exception:
            log_structured("warning", "gitops_issue_failed", title=title, exc_info=True)
            return {FieldName.STATUS: "error", FieldName.REASON: "github_api_error"}
        log_structured("info", "gitops_issue_opened", title=title, issue_url=issue_url)
        return {FieldName.STATUS: "opened", FieldName.PR_URL: issue_url}

    # -- GitHub REST helpers (response keys are GitHub API contract strings) --

    async def _base_sha(self, client: httpx.AsyncClient) -> str | None:
        resp = await client.get(f"/repos/{self.repo}/git/ref/heads/{self.base_branch}")
        if resp.status_code != 200:
            return None
        return resp.json().get("object", {}).get("sha")

    async def _create_branch(self, client: httpx.AsyncClient, branch: str, sha: str) -> None:
        resp = await client.post(
            f"/repos/{self.repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        resp.raise_for_status()

    async def _put_file(
        self, client: httpx.AsyncClient, path: str, content: dict[str, Any], branch: str, msg: str
    ) -> None:
        # Structural config-only guarantee: auto-PR may ONLY write under the
        # config-overrides dir, never source code. Anything else needs an issue.
        if not path.startswith(f"{PARAMETER_OVERRIDES_DIR}/"):
            raise ValueError(f"auto-PR refused: {path} is outside {PARAMETER_OVERRIDES_DIR}")
        encoded = base64.b64encode(json.dumps(content, indent=2).encode()).decode()
        resp = await client.put(
            f"/repos/{self.repo}/contents/{path}",
            json={"message": msg, "content": encoded, "branch": branch},
        )
        resp.raise_for_status()

    async def _open_pr(self, client: httpx.AsyncClient, branch: str, title: str, body: str) -> str:
        resp = await client.post(
            f"/repos/{self.repo}/pulls",
            json={"title": title, "head": branch, "base": self.base_branch, "body": body},
        )
        resp.raise_for_status()
        return str(resp.json().get("html_url") or "")
