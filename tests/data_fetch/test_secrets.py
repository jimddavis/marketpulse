"""WS-C — DotenvSecretResolver / DatabricksSecretResolver unit tests. No network."""

from __future__ import annotations

import pytest

from data_fetch.secrets import (
    DatabricksSecretResolver,
    DotenvSecretResolver,
    SecretResolver,
)

from fakes import FakeDbutils


# -- DotenvSecretResolver ----------------------------------------------------

def test_dotenv_reads_key(tmp_path):
    (tmp_path / ".env").write_text("FRED_API_KEY=abc123\n")
    resolver = DotenvSecretResolver(start_dir=str(tmp_path))
    assert resolver.get("FRED_API_KEY") == "abc123"
    assert isinstance(resolver, SecretResolver)


def test_dotenv_walks_up_to_find_env(tmp_path):
    (tmp_path / ".env").write_text("FRED_API_KEY=parent-key\n")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    resolver = DotenvSecretResolver(start_dir=str(nested))
    assert resolver.get("FRED_API_KEY") == "parent-key"


def test_dotenv_ignores_comments_blanks_and_strips_quotes(tmp_path):
    (tmp_path / ".env").write_text(
        "# a comment\n"
        "\n"
        'FRED_API_KEY="quoted-key"\n'
        "OTHER=plain\n"
    )
    resolver = DotenvSecretResolver(start_dir=str(tmp_path))
    assert resolver.get("FRED_API_KEY") == "quoted-key"
    assert resolver.get("OTHER") == "plain"


def test_dotenv_missing_key_raises_keyerror(tmp_path):
    (tmp_path / ".env").write_text("OTHER=x\n")
    resolver = DotenvSecretResolver(start_dir=str(tmp_path))
    with pytest.raises(KeyError, match="FRED_API_KEY"):
        resolver.get("FRED_API_KEY")


def test_dotenv_no_file_raises(tmp_path):
    resolver = DotenvSecretResolver(start_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        resolver.get("FRED_API_KEY")


# -- DatabricksSecretResolver (Projected — §14 Q7) ---------------------------

def test_databricks_reads_widget_by_default():
    dbutils = FakeDbutils(widgets={"FRED_API_KEY": "widget-key"})
    resolver = DatabricksSecretResolver(dbutils)
    assert resolver.get("FRED_API_KEY") == "widget-key"
    assert dbutils.widgets.calls == ["FRED_API_KEY"]
    assert isinstance(resolver, SecretResolver)


def test_databricks_uses_secret_scope_when_given():
    dbutils = FakeDbutils(secrets={("marketpulse", "FRED_API_KEY"): "scoped-key"})
    resolver = DatabricksSecretResolver(dbutils, scope="marketpulse")
    assert resolver.get("FRED_API_KEY") == "scoped-key"
    assert dbutils.secrets.calls == [("marketpulse", "FRED_API_KEY")]
