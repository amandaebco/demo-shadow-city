"""HTTP client for Track A's System One (/v1/decide) service (CONTRACT.md section 4)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from typing import Any

import google.auth.transport.requests
import google.oauth2.id_token
import requests

logger = logging.getLogger("sim_worker.system_one")

MAX_BATCH_SIZE = 256
DEFAULT_TIMEOUT_SEC = 120


def _is_cloud_run_environment() -> bool:
    """Return True when running inside Cloud Run Service or Cloud Run Job."""
    return bool(os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_JOB"))


class SystemOneClient:
    """Client for POST /v1/decide on Cloud Run service system-one."""

    def __init__(
        self,
        base_url: str,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self._session = session or requests.Session()
        self._cached_token: str | None = None
        self._token_expiry: float = 0.0

    def _fetch_gcloud_cli_token(self) -> str | None:
        gcloud_bin = shutil.which("gcloud") or shutil.which("gcloud.cmd")
        if not gcloud_bin:
            return None
        try:
            out = subprocess.check_output(
                [gcloud_bin, "auth", "print-identity-token"],
                text=True,
                timeout=15,
            ).strip()
            return out or None
        except Exception as exc:
            logger.debug("gcloud auth print-identity-token failed: %s", exc)
            return None

    def _fetch_metadata_id_token(self) -> str | None:
        try:
            auth_req = google.auth.transport.requests.Request()
            token = google.oauth2.id_token.fetch_id_token(auth_req, self.base_url)
            return token or None
        except Exception as exc:
            logger.debug("fetch_id_token unavailable: %s", exc)
            return None

    def _get_id_token(self) -> str | None:
        if self.base_url.startswith("http://localhost") or self.base_url.startswith(
            "http://127.0.0.1"
        ):
            return None

        now = time.time()
        if self._cached_token and now < self._token_expiry:
            return self._cached_token

        if _is_cloud_run_environment():
            token = self._fetch_metadata_id_token() or self._fetch_gcloud_cli_token()
        else:
            # Local runs: use gcloud auth print-identity-token first, fallback to SA metadata/ADC
            token = self._fetch_gcloud_cli_token() or self._fetch_metadata_id_token()

        if token:
            self._cached_token = token
            self._token_expiry = now + 2400  # Cache for 40 minutes
            return token

        logger.warning("Could not obtain identity token for System One (%s)", self.base_url)
        return None

    def decide_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Send decision request items in batches of up to 256 items and return responses in order."""
        if not items:
            return []

        all_responses: list[dict[str, Any]] = []
        for start in range(0, len(items), MAX_BATCH_SIZE):
            chunk = items[start : start + MAX_BATCH_SIZE]
            headers = {"Content-Type": "application/json"}
            token = self._get_id_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

            url = f"{self.base_url}/v1/decide"
            logger.info("Calling System One %s with batch of %d items...", url, len(chunk))
            resp = self._session.post(
                url,
                json={"items": chunk},
                headers=headers,
                timeout=self.timeout_sec,
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"System One /v1/decide failed with HTTP {resp.status_code}: {resp.text[:500]}"
                )
            payload = resp.json()
            batch_items = payload.get("items")
            if not isinstance(batch_items, list) or len(batch_items) != len(chunk):
                raise RuntimeError(
                    f"System One returned {len(batch_items) if isinstance(batch_items, list) else 'invalid'} "
                    f"items for batch of {len(chunk)}"
                )
            all_responses.extend(batch_items)

        return all_responses
