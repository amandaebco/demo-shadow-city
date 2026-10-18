"""HTTP client for Track A's System One (/v1/decide) service (CONTRACT.md section 4)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import os
import shutil
import subprocess
import time
from typing import Any

import google.auth
import google.auth.transport.requests
import google.oauth2.id_token
import requests

logger = logging.getLogger("sim_worker.system_one")

MAX_BATCH_SIZE = 256
SAFE_HTTP_CHUNK_SIZE = 64
DEFAULT_TIMEOUT_SEC = 300


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

    def _fetch_adc_id_token(self) -> str | None:
        try:
            creds, _ = google.auth.default()
            auth_req = google.auth.transport.requests.Request()
            creds.refresh(auth_req)
            token = getattr(creds, "id_token", None)
            return str(token) if token else None
        except Exception as exc:
            logger.debug("ADC id_token refresh failed: %s", exc)
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
            token = (
                self._fetch_metadata_id_token()
                or self._fetch_adc_id_token()
                or self._fetch_gcloud_cli_token()
            )
        else:
            token = (
                self._fetch_adc_id_token()
                or self._fetch_gcloud_cli_token()
                or self._fetch_metadata_id_token()
            )

        if token:
            self._cached_token = token
            self._token_expiry = now + 2400  # Cache for 40 minutes
            return token

        logger.warning("Could not obtain identity token for System One (%s)", self.base_url)
        return None

    def _post_chunk(
        self, url: str, headers: dict[str, str], chunk: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        logger.info("Calling System One %s with batch of %d items...", url, len(chunk))
        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                resp = requests.post(
                    url,
                    json={"items": chunk},
                    headers=headers,
                    timeout=self.timeout_sec,
                )
                if resp.status_code in (502, 503, 504) and attempt < 3:
                    logger.warning(
                        "System One HTTP %d on attempt %d for %d items; retrying...",
                        resp.status_code,
                        attempt,
                        len(chunk),
                    )
                    time.sleep(2 * attempt)
                    continue
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
                return batch_items
            except Exception as exc:
                last_err = exc
                if attempt < 3:
                    time.sleep(2 * attempt)
                else:
                    raise
        raise RuntimeError(f"System One /v1/decide failed: {last_err}")

    def decide_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Send decision request items batched per tick (<= 256 items per call) and return in order."""
        if not items:
            return []

        headers = {"Content-Type": "application/json"}
        token = self._get_id_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url = f"{self.base_url}/v1/decide"
        chunk_limit = min(MAX_BATCH_SIZE, SAFE_HTTP_CHUNK_SIZE)
        chunks = [
            items[start : start + chunk_limit]
            for start in range(0, len(items), chunk_limit)
        ]

        if len(chunks) == 1:
            return self._post_chunk(url, headers, chunks[0])

        all_responses: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(2, len(chunks))) as pool:
            futures = [pool.submit(self._post_chunk, url, headers, c) for c in chunks]
            for fut in futures:
                all_responses.extend(fut.result())
        return all_responses
