"""The secret store (stage F4; ADR-0092): one interface, several places, never a value in the
open."""

import json
import logging
import os
import stat

import pytest
from wasifyai_platform_sdk import (
    EnvSecretStore,
    FileSecretStore,
    InMemorySecretStore,
    KeychainSecretStore,
    LayeredSecretStore,
    SecretBox,
    SecretsUnavailable,
    SqlSecretStore,
    secret_name,
)
from wasifyai_platform_sdk.sqlite import create_sqlite_engine

VALUE = "hf_abcdefghijklmnopqrstuvwxyz0123"


def stores(tmp_path):
    box = SecretBox(SecretBox.generate_key())
    yield "memory", InMemorySecretStore()
    yield "file", FileSecretStore(tmp_path / "secrets.json", box)
    yield "sql", SqlSecretStore(create_sqlite_engine(tmp_path / "app.db"), box)


@pytest.mark.parametrize("kind", ["memory", "file", "sql"])
async def test_every_store_keeps_finds_lists_and_forgets_by_name(tmp_path, kind):
    store = dict(stores(tmp_path))[kind]
    assert store.ready
    assert await store.get("hf.token") is None and await store.names() == []
    await store.put("hf.token", VALUE)
    await store.put("web.search.exa", "exa-key-1")
    assert await store.get("hf.token") == VALUE
    assert await store.names() == ["hf.token", "web.search.exa"]
    await store.put("hf.token", "hf_replaced00000000000000000")
    assert await store.get("hf.token") == "hf_replaced00000000000000000"
    await store.delete("hf.token")
    await store.delete("hf.token")  # twice is fine
    assert await store.get("hf.token") is None and await store.names() == ["web.search.exa"]


@pytest.mark.parametrize("bad", ["", "HF.TOKEN", "hf", "hf token", "a" * 101, "hf.", ".x"])
def test_a_name_is_lower_case_words_joined_by_dots(bad):
    with pytest.raises(ValueError, match="joined by dots"):
        secret_name(bad)


async def test_the_file_is_private_and_holds_no_value_in_the_open(tmp_path):
    path = tmp_path / "secrets.json"
    store = FileSecretStore(path, SecretBox(SecretBox.generate_key()))
    await store.put("hf.token", VALUE)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    body = path.read_text()
    assert VALUE not in body and set(json.loads(body)) == {"hf.token"}


async def test_the_sql_table_holds_no_value_in_the_open(tmp_path):
    from sqlalchemy import text

    engine = create_sqlite_engine(tmp_path / "app.db")
    store = SqlSecretStore(engine, SecretBox(SecretBox.generate_key()))
    await store.put("hf.token", VALUE)
    async with engine.connect() as conn:
        rows = [dict(r._mapping) for r in await conn.execute(text("SELECT * FROM secrets"))]
    assert len(rows) == 1 and rows[0]["name"] == "hf.token" and VALUE not in rows[0]["value"]


async def test_a_store_with_another_key_says_so_instead_of_answering_garbage(tmp_path):
    path = tmp_path / "secrets.json"
    await FileSecretStore(path, SecretBox(SecretBox.generate_key())).put("hf.token", VALUE)
    with pytest.raises(SecretsUnavailable, match="enter it again"):
        await FileSecretStore(path, SecretBox(SecretBox.generate_key())).get("hf.token")
    no_key = FileSecretStore(path, SecretBox(""))
    assert not no_key.ready
    with pytest.raises(SecretsUnavailable):
        await no_key.put("hf.token", VALUE)


async def test_the_environment_answers_by_name_and_alias_but_cannot_be_changed(monkeypatch):
    monkeypatch.setenv("WASIFYAI_SECRET_WEB_SEARCH_EXA", "exa-from-env")
    monkeypatch.setenv("HF_TOKEN", VALUE)
    env = EnvSecretStore({"hf.token": ("HF_TOKEN",)})
    assert not env.ready
    assert EnvSecretStore.variable("web.search.exa") == "WASIFYAI_SECRET_WEB_SEARCH_EXA"
    assert await env.get("web.search.exa") == "exa-from-env"
    assert await env.get("hf.token") == VALUE
    assert await env.get("nothing.here") is None
    assert await env.names() == ["hf.token", "web.search.exa"]
    with pytest.raises(SecretsUnavailable):
        await env.put("hf.token", "x")


async def test_a_layered_store_writes_in_front_and_reads_through(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "hf_fromtheenvironment0000000000")
    front = InMemorySecretStore()
    store = LayeredSecretStore(front, EnvSecretStore({"hf.token": ("HF_TOKEN",)}))
    assert await store.get("hf.token") == "hf_fromtheenvironment0000000000"
    await store.put("hf.token", VALUE)
    assert await store.get("hf.token") == VALUE and await front.get("hf.token") == VALUE
    await store.delete("hf.token")
    assert (
        await store.get("hf.token") == "hf_fromtheenvironment0000000000"
    )  # the env is still there
    assert await store.names() == ["hf.token"]


async def test_nothing_is_logged_when_a_secret_is_kept_or_read(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    store = FileSecretStore(tmp_path / "secrets.json", SecretBox(SecretBox.generate_key()))
    await store.put("hf.token", VALUE)
    await store.get("hf.token")
    await store.names()
    assert VALUE not in caplog.text


@pytest.mark.skipif(
    not KeychainSecretStore.available() or os.environ.get("WASIFYAI_TEST_KEYCHAIN") != "1",
    reason="touches the macOS keychain of the person running the tests: WASIFYAI_TEST_KEYCHAIN=1",
)
async def test_the_macos_keychain_keeps_a_secret_under_the_apps_name(tmp_path):
    store = KeychainSecretStore("Wasify AI (test)", tmp_path / "names.json")
    name = "test.keychain-secret"
    try:
        await store.put(name, VALUE)
        assert await store.get(name) == VALUE
        assert await store.names() == [name]
        await store.put(name, "hf_second0000000000000000000")
        assert await store.get(name) == "hf_second0000000000000000000"
    finally:
        await store.delete(name)
    assert await store.get(name) is None and await store.names() == []
    assert VALUE not in (tmp_path / "names.json").read_text()
