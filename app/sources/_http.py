"""Cliente HTTP com cache em disco e throttle — compartilhado pelas fontes."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests

from ..config import HTTP_HEADERS

_LAST_CALL: dict[str, float] = {}


class HttpClient:
    def __init__(
        self,
        *,
        cache_dir: str | Path | None = ".cache",
        cache_ttl_s: int = 1800,
        gap_s: float = 0.0,
        headers: dict[str, str] | None = None,
        timeout: int = 20,
        retries: int = 2,
    ) -> None:
        self.retries = retries
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_s = cache_ttl_s
        self.gap_s = gap_s
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HTTP_HEADERS)
        if headers:
            self.session.headers.update(headers)
        self.last_headers: dict[str, str] = {}

    # ── cache ────────────────────────────────────────────────────────────────
    def _cache_path(self, url: str, params: dict[str, Any] | None) -> Path | None:
        if not self.cache_dir:
            return None
        raw = url + "?" + json.dumps(params or {}, sort_keys=True)
        digest = hashlib.sha1(raw.encode()).hexdigest()[:16]
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, path: Path | None) -> Any | None:
        if not path or not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.cache_ttl_s:
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    # ── request ──────────────────────────────────────────────────────────────
    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        host_key: str = "default",
        retries: int | None = None,
    ) -> Any:
        cache_path = self._cache_path(url, params)
        cached = self._read_cache(cache_path)
        if cached is not None:
            return cached

        retries = retries if retries is not None else self.retries
        last_err: Exception | None = None
        for attempt in range(retries):
            self._throttle(host_key)
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                self.last_headers = dict(resp.headers)
                if resp.status_code == 200:
                    data = resp.json()
                    if cache_path:
                        cache_path.write_text(json.dumps(data))
                    return data
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = RuntimeError(f"HTTP {resp.status_code} em {url}")
                    time.sleep(0.8 * (attempt + 1))
                    continue
                resp.raise_for_status()
            except (requests.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(0.8 * (attempt + 1))
        raise RuntimeError(f"Falha ao buscar {url}: {last_err}")

    def _throttle(self, host_key: str) -> None:
        if self.gap_s <= 0:
            return
        prev = _LAST_CALL.get(host_key, 0.0)
        wait = self.gap_s - (time.time() - prev)
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[host_key] = time.time()
