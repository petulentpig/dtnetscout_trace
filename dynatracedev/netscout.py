"""Minimal REST client for pulling network-transaction records from NetScout.

The request/response shape of the NetScout REST API (nGeniusONE and friends)
varies by product and version, so this client is deliberately generic: point it
at an endpoint that returns a JSON array of transaction records -- optionally
nested under a key (``records_json_path``) -- and let :class:`RecordMapper`
interpret the fields. Adjust :meth:`fetch_records` for your product's exact
query parameters (time window, filters, paging).
"""

from __future__ import annotations

from dataclasses import dataclass

import requests


class NetScoutError(Exception):
    """A NetScout request failed or returned an unusable body."""


@dataclass
class NetScoutConfig:
    base_url: str
    records_path: str
    records_json_path: str = ""
    api_token: str = ""
    username: str = ""
    password: str = ""
    verify_tls: bool = True
    lookback_seconds: int = 120
    timeout_seconds: int = 30


class NetScoutClient:
    def __init__(self, config: NetScoutConfig):
        self.config = config
        self._session = requests.Session()
        if config.api_token:
            self._session.headers["Authorization"] = f"Bearer {config.api_token}"
        elif config.username:
            self._session.auth = (config.username, config.password)

    def fetch_records(self, since_epoch_s: float) -> list[dict]:
        """Fetch network-transaction records observed since ``since_epoch_s``."""
        cfg = self.config
        url = cfg.base_url.rstrip("/") + "/" + cfg.records_path.lstrip("/")
        # NOTE: adjust these params to your NetScout API's time-window contract.
        params = {"since": int(since_epoch_s)}
        try:
            resp = self._session.get(
                url,
                params=params,
                verify=cfg.verify_tls,
                timeout=cfg.timeout_seconds,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise NetScoutError(f"NetScout request to {url} failed: {exc}") from exc
        except ValueError as exc:
            raise NetScoutError(f"NetScout returned a non-JSON body: {exc}") from exc
        return self._extract(payload)

    def _extract(self, payload) -> list[dict]:
        if self.config.records_json_path:
            for part in self.config.records_json_path.split("."):
                payload = payload.get(part) if isinstance(payload, dict) else None
                if payload is None:
                    return []
        if payload is None:
            return []
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return [record for record in payload if isinstance(record, dict)]
        raise NetScoutError(f"unexpected NetScout payload shape: {type(payload).__name__}")
