"""Reusable test fakes — no network, no Spark.

Grows as WS-A…F land (design §11, WS-H). Imported by sibling test modules via
`from fakes import ...` (pytest prepends the test dir to sys.path).
"""

from __future__ import annotations

import json
from typing import Any, Iterable


class FakeResponse:
    """Minimal stand-in for a streamed requests.Response used as a context manager."""

    def __init__(self, status_code: int, *, headers: dict[str, str] | None = None,
                 body: bytes = b"", chunks: Iterable[bytes] | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks) if chunks is not None else [body]

    def iter_content(self, chunk_size: int = 65536):
        yield from self._chunks

    @property
    def content(self) -> bytes:
        return b"".join(self._chunks)

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class FakeSession:
    """Returns queued FakeResponses in order; records each call's args for assertions."""

    def __init__(self, responses: Iterable[FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, headers: dict | None = None, stream: bool = False,
            timeout: Any = None, params: dict | None = None) -> FakeResponse:
        self.calls.append({"url": url, "headers": dict(headers or {}), "stream": stream,
                           "timeout": timeout, "params": params})
        if not self._responses:
            raise AssertionError(f"FakeSession: no queued response for GET {url}")
        return self._responses.pop(0)


class FakeSecretResolver:
    """In-memory SecretResolver for FRED tests — never touches os.environ."""

    def __init__(self, **secrets: str):
        self._secrets = secrets

    def get(self, key: str) -> str:
        return self._secrets[key]


class _FakeWidgets:
    def __init__(self, values: dict[str, str]):
        self._values = values
        self.calls: list[str] = []

    def get(self, key: str) -> str:
        self.calls.append(key)
        return self._values[key]


class _FakeSecrets:
    def __init__(self, values: dict[tuple[str, str], str]):
        self._values = values
        self.calls: list[tuple[str, str]] = []

    def get(self, scope: str, key: str) -> str:
        self.calls.append((scope, key))
        return self._values[(scope, key)]


class FakeDbutils:
    """Stand-in for the Databricks `dbutils` handle — exposes .widgets and .secrets."""

    def __init__(self, widgets: dict[str, str] | None = None,
                 secrets: dict[tuple[str, str], str] | None = None):
        self.widgets = _FakeWidgets(widgets or {})
        self.secrets = _FakeSecrets(secrets or {})


class _FakeDeltaWriter:
    def __init__(self, df: "_FakeDataFrame"):
        self._df = df
        self._fmt: str | None = None
        self._mode: str | None = None

    def format(self, fmt: str) -> "_FakeDeltaWriter":
        self._fmt = fmt
        return self

    def mode(self, mode: str) -> "_FakeDeltaWriter":
        self._mode = mode
        return self

    def saveAsTable(self, table: str) -> None:
        spark = self._df._spark
        if spark.fail_on_write:
            raise RuntimeError("simulated write failure")
        spark.writes.append({"table": table, "format": self._fmt, "mode": self._mode,
                             "data": self._df.data, "schema": self._df.schema})


class _FakeDataFrame:
    def __init__(self, spark: "FakeSpark", data: list, schema: Any):
        self._spark = spark
        self.data = data
        self.schema = schema

    @property
    def write(self) -> _FakeDeltaWriter:
        return _FakeDeltaWriter(self)


class _FakeSqlResult:
    def __init__(self, rows: list):
        self._rows = rows

    def collect(self) -> list:
        return self._rows


class FakeSpark:
    """Captures createDataFrame→write.saveAsTable and spark.sql(...) for audit-logging
    tests. Not a real session — only the surface download_log_* touches.

    `sql_results` is a queue: each spark.sql() call pops the next list-of-rows (rows are
    dicts supporting `row["col"]`). `fail_on_write` / `fail_on_sql` simulate failures to
    exercise the swallow-and-return contract.
    """

    def __init__(self, sql_results: list[list] | None = None,
                 fail_on_write: bool = False, fail_on_sql: bool = False):
        self.writes: list[dict] = []
        self.sql_calls: list[dict] = []
        self._sql_results = list(sql_results or [])
        self.fail_on_write = fail_on_write
        self.fail_on_sql = fail_on_sql

    def createDataFrame(self, data: list, schema: Any = None) -> _FakeDataFrame:
        return _FakeDataFrame(self, list(data), schema)

    def sql(self, query: str, args: dict | None = None) -> _FakeSqlResult:
        self.sql_calls.append({"query": query, "args": args})
        if self.fail_on_sql:
            raise RuntimeError("simulated sql failure")
        rows = self._sql_results.pop(0) if self._sql_results else []
        return _FakeSqlResult(rows)
