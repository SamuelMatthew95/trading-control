"""GitOps auto-PR publisher — turns a parameter-change proposal into a real PR.

When the learning loop approves a `PARAMETER_CHANGE`, the ProposalApplier emits
a `pr_request` artifact AND (via this module) opens a pull request that edits a
**config file** — never raw source code — so the change is version-controlled
and human-reviewed before it can affect anything.

The PR edits ``config/param_overrides.json`` — the SAME validated overrides
file the GitHub Action path (``param-evolution-pr.yml`` →
``apply_param_change.py``) edits and that ``api/constants.py`` loads at import
time. One artifact format, one loader, one safe-bounds validator
(``param_evolution.validate_param_change``); a junk or out-of-bounds change is
refused before any branch or PR exists. A human merges the PR; nothing in the
live system changes until the next deploy reads the merged file.

Safety: this only acts when ``GITHUB_AUTOPR_ENABLED`` is set AND a token + repo
are configured (``GITHUB_TOKEN`` lives in the Render env). With no token/repo —
local dev, tests, CI — every call is a **dry-run no-op** that touches no network.
All failures are swallowed: a GitOps hiccup must never break the trading loop.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

import httpx

from api.config import settings
from api.constants import FieldName
from api.observability import log_structured
from api.services.param_evolution import validate_param_change
from api.services.param_overrides import DEFAULT_OVERRIDES_PATH, apply_param_override

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
        """Open a PR applying the parameter change to ``config/param_overrides.json``.

        Returns a status dict — ``{status: dry_run}`` when not configured,
        ``{status: rejected, reason}`` when the change fails safe-bounds
        validation (refused BEFORE any branch/PR exists),
        ``{status: opened, pr_url}`` on success, ``{status: error}`` on
        failure. Never raises.
        """
        if not _autopr_ready():
            return {FieldName.STATUS: "dry_run"}

        parameter = str(artifact.get(FieldName.PARAMETER) or "").strip()
        proposed = artifact.get(FieldName.PROPOSED_VALUE)
        err = validate_param_change(parameter, proposed)
        if err is not None:
            log_structured("warning", "gitops_autopr_rejected", parameter=parameter, reason=err)
            return {FieldName.STATUS: "rejected", FieldName.REASON: err}

        previous = artifact.get(FieldName.PREVIOUS_VALUE)
        reason = str(artifact.get(FieldName.REASON) or "")
        branch = f"auto/param-{parameter.lower()}-{uuid.uuid4().hex[:8]}"
        title = f"[auto] param {parameter}: {previous} → {proposed}"
        body = (
            f"Automated parameter-change proposal from the learning loop.\n\n"
            f"- **parameter**: `{parameter}`\n"
            f"- **previous**: `{previous}`\n"
            f"- **proposed**: `{proposed}`\n"
            f"- **reason**: {reason}\n"
            f"- **trace_id**: `{artifact.get(FieldName.TRACE_ID)}`\n\n"
            f"This PR edits the validated config-overrides file only (no source "
            f"code); `api/constants.py` re-validates and applies it on the next "
            f"deploy. Review and merge to adopt."
        )

        try:
            async with httpx.AsyncClient(
                base_url=_GITHUB_API, headers=self._headers(), timeout=_HTTP_TIMEOUT
            ) as client:
                base_sha = await self._base_sha(client)
                if not base_sha:
                    return {FieldName.STATUS: "error", FieldName.REASON: "base_ref_not_found"}
                # Read-modify-write the overrides document BEFORE creating any
                # branch, so a no-op/refused change leaves no orphan branches.
                current_text, file_sha = await self._get_overrides_file(client)
                ok, new_text, apply_err = apply_param_override(current_text, parameter, proposed)
                if not ok or new_text is None:
                    log_structured(
                        "info", "gitops_autopr_no_change", parameter=parameter, reason=apply_err
                    )
                    return {FieldName.STATUS: "rejected", FieldName.REASON: apply_err}
                await self._create_branch(client, branch, base_sha)
                await self._put_file(
                    client, str(DEFAULT_OVERRIDES_PATH), new_text, branch, title, sha=file_sha
                )
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

    async def _get_overrides_file(self, client: httpx.AsyncClient) -> tuple[str, str | None]:
        """Current text + blob sha of the overrides file on the base branch.

        Returns ``("", None)`` when the file does not exist yet (first override).
        """
        resp = await client.get(
            f"/repos/{self.repo}/contents/{DEFAULT_OVERRIDES_PATH}",
            params={"ref": self.base_branch},
        )
        if resp.status_code == 404:
            return "", None
        resp.raise_for_status()
        payload = resp.json()
        # "content" is the GitHub contents-API key; FieldName.CONTENT serializes
        # to the same string, satisfying the no-raw-FieldName-reads guardrail.
        text = base64.b64decode(payload.get(FieldName.CONTENT) or "").decode("utf-8")
        return text, payload.get("sha")

    async def _put_file(
        self,
        client: httpx.AsyncClient,
        path: str,
        content_text: str,
        branch: str,
        msg: str,
        *,
        sha: str | None = None,
    ) -> None:
        # Structural config-only guarantee: auto-PR may ONLY write the validated
        # overrides document, never source code. Anything else needs an issue.
        if path != str(DEFAULT_OVERRIDES_PATH):
            raise ValueError(f"auto-PR refused: {path} is outside {DEFAULT_OVERRIDES_PATH}")
        body: dict[str, Any] = {
            "message": msg,
            "content": base64.b64encode(content_text.encode()).decode(),
            "branch": branch,
        }
        if sha:  # required by the contents API when updating an existing file
            body["sha"] = sha
        resp = await client.put(f"/repos/{self.repo}/contents/{path}", json=body)
        resp.raise_for_status()

    async def _open_pr(self, client: httpx.AsyncClient, branch: str, title: str, body: str) -> str:
        resp = await client.post(
            f"/repos/{self.repo}/pulls",
            json={"title": title, "head": branch, "base": self.base_branch, "body": body},
        )
        resp.raise_for_status()
        return str(resp.json().get("html_url") or "")
