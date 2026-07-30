"""HTTP client for the local JobPilot API.

Slack never touches the database. Every button it renders ends up calling the
same REST endpoint the web dashboard calls, so the two can't drift apart —
Postgres stays the single source of truth (PLAN.md §10). The cost is one extra
hop on localhost, which is worth it for having exactly one code path per action.
"""

from __future__ import annotations

from typing import Any

import httpx

from jobpilot.config import get_secrets

DEFAULT_BASE = "http://127.0.0.1:8000"


class ApiError(RuntimeError):
    """The API rejected the call. ``detail`` is safe to show in Slack."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class JobPilotClient:
    """Thin wrapper over the REST API.

    ``http_client`` lets tests inject Starlette's ``TestClient`` (itself an
    ``httpx.Client``) so the exact code Slack runs is exercised against the real
    routes without starting a server.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE,
        token: str | None = None,
        timeout: float = 180.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token if token is not None else get_secrets().jobpilot_api_token
        self._owns_client = http_client is None
        # Tailor and apply are slow (a Claude call plus a Docker build), so the
        # default timeout is generous rather than the usual few seconds.
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "JobPilotClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ----------------------------------------------------------------- #
    def _request(self, method: str, path: str, **kwargs) -> Any:
        # Auth per request rather than on the client, so an injected client
        # keeps whatever headers its owner configured.
        headers = {"X-API-Token": self.token, **kwargs.pop("headers", {})}
        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(0, f"cannot reach the JobPilot API at {self.base_url} ({exc})") from exc
        if response.status_code >= 400:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
            raise ApiError(response.status_code, str(detail))
        return None if response.status_code == 204 else response.json()

    @staticmethod
    def _job_path(job_id: str) -> str:
        # Job ids contain ':' — legal in a path segment, but encode anything else.
        from urllib.parse import quote

        return f"/jobs/{quote(job_id, safe=':')}"

    # ----------------------------------------------------------------- #
    def health(self) -> dict:
        return self._request("GET", "/health")

    def jobs(self, **query) -> list[dict]:
        return self._request("GET", "/jobs", params={k: v for k, v in query.items() if v})

    def job(self, job_id: str) -> dict:
        return self._request("GET", self._job_path(job_id))

    def stats(self) -> dict:
        return self._request("GET", "/stats")

    def shortlist(self, job_id: str) -> dict:
        return self._request("POST", f"{self._job_path(job_id)}/shortlist")

    def skip(self, job_id: str) -> dict:
        return self._request("POST", f"{self._job_path(job_id)}/skip")

    def tailor(self, job_id: str) -> dict:
        """Queue a tailor round. Returns the task, not the result — the review
        card arrives later, over the WebSocket mirror."""
        return self._request("POST", f"{self._job_path(job_id)}/tailor")

    def edit(self, job_id: str, instruction: str) -> dict:
        return self._request(
            "POST", f"{self._job_path(job_id)}/edit", json={"instruction": instruction}
        )

    def task(self, task_id: str) -> dict:
        """One background task. The queue keeps the last 50, so an old id 404s."""
        return self._request("GET", f"/tasks/{task_id}")

    def review(self, job_id: str) -> dict:
        return self._request("GET", f"{self._job_path(job_id)}/review")

    def approve(self, job_id: str) -> dict:
        return self._request("POST", f"{self._job_path(job_id)}/approve")

    def reject(self, job_id: str) -> dict:
        return self._request("POST", f"{self._job_path(job_id)}/reject")

    def apply(self, job_id: str) -> dict:
        return self._request("POST", f"{self._job_path(job_id)}/apply")

    def confirm_submit(self, job_id: str) -> dict:
        return self._request("POST", f"{self._job_path(job_id)}/confirm-submit")

    def report_failure(self, job_id: str, reason: str) -> dict:
        return self._request(
            "POST", f"{self._job_path(job_id)}/report-failure", json={"reason": reason}
        )

    def applications(self, result: str | None = None) -> list[dict]:
        return self._request("GET", "/applications", params={"result": result} if result else None)

    def apply_settings(self) -> dict:
        return self._request("GET", "/applications/settings")
