"""SecretResolver Adapter protocol (WS0).

The one environment seam notebook_init does not inject — the FRED API key. Resolution
is environment-specific (.env locally, dbutils on Databricks); concrete resolvers
(DotenvSecretResolver, DatabricksSecretResolver) are WS-C. FredApiProvider calls
`secrets.get(spec.api_key_env)`, never `os.environ` directly (design §8.1, §16.5).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SecretResolver(Protocol):
    def get(self, key: str) -> str:
        """Return the secret value for `key` (== SourceSpec.api_key_env)."""
        ...


class DotenvSecretResolver:
    """Local resolver — reads a project-root `.env`, discovered by walking up from a
    start directory (design §8.1, §16). Minimal KEY=VALUE parser, no python-dotenv
    dependency; values are cached on first read. No `os.environ` fallback by design —
    the .env file is the single local secret source.
    """

    def __init__(self, start_dir: str | None = None, env_filename: str = ".env"):
        self._start_dir = start_dir or os.getcwd()
        self._env_filename = env_filename
        self._cache: dict[str, str] | None = None

    def get(self, key: str) -> str:
        if self._cache is None:
            self._cache = self._load()
        try:
            return self._cache[key]
        except KeyError:
            raise KeyError(
                f"{key!r} not found in {self._env_filename} "
                f"(searched up from {self._start_dir})"
            ) from None

    def _load(self) -> dict[str, str]:
        path = self._find_env()
        if path is None:
            raise FileNotFoundError(
                f"No {self._env_filename} found searching up from {self._start_dir}"
            )
        values: dict[str, str] = {}
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip().strip('"').strip("'")
        return values

    def _find_env(self) -> str | None:
        start = Path(self._start_dir).resolve()
        for candidate in (start, *start.parents):
            env_path = candidate / self._env_filename
            if env_path.is_file():
                return str(env_path)
        return None


class DatabricksSecretResolver:
    """Databricks resolver via the injected `dbutils`.

    CONFIDENCE: Projected (design §14 Q7 — OPEN). The channel for the FRED key on Free
    Edition is unverified: secret scopes may be unavailable, in which case the key is
    passed as a job/widget parameter. This resolver defaults to reading a notebook
    **widget** (job parameters surface as widgets on a notebook_task), the Free-Edition-
    safe path; pass `scope=` to use dbutils.secrets.get(scope, key) instead. VERIFY at
    WS-I before relying on either path.
    """

    def __init__(self, dbutils: Any, *, scope: str | None = None):
        self._dbutils = dbutils
        self._scope = scope

    def get(self, key: str) -> str:
        if self._scope is not None:
            return self._dbutils.secrets.get(scope=self._scope, key=key)
        return self._dbutils.widgets.get(key)
