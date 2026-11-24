"""Harnesses (ADR-0107; stage H1): the person's own agent program as a coding session.

What is checked here, without a model, a network or the programs themselves:

    names        a harness's model is `<harness>:<model>`, and anything else is Wasify AI's
    sign-in      of the program's own status only "signed in", how and the plan's name are kept;
                 a sign-in's page is shown only when it is the provider's; the program is given
                 the person's home and nothing of this engine's environment
    proxy        a harness reaches its own provider's hosts and nothing else; the agent and the
                 person never reach a provider
    profile      a harness's server opens its program's sign-in folders, the keychain and the
                 programs; the Wasify AI server opens none of it
    a session    on the fake Agent Server: an `acp` conversation with the program's command and
                 no token of ours; the program's steps in our words; what it used reported once

The sandbox itself is checked on the real server in `tests/integration/test_coding_sandbox.py`.
"""

import asyncio
import base64
import json
import stat
import sys
from pathlib import Path

import pytest
from wasifyai_api.coding_harness import (
    HARNESSES,
    HarnessAccounts,
    acp_command,
    find_harness_install,
    harness_of,
    page_of,
    read_status,
)
from wasifyai_api.coding_proxy import AGENT, PERSON, InstallProxy
from wasifyai_api.coding_server import CodingError, fill_profile
from wasifyai_code import place as places
from wasifyai_code.client import HARNESS_READ_ONLY_NOTE, ThisComputer
from wasifyai_code.events import Reader
from wasifyai_code.place import SessionSpec, harness_model

from .test_coding_server import install, real, server

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the fake server is a shell script")

FIXTURES = Path(__file__).with_name("fixtures") / "coding"
CLAUDE, CODEX = HARNESSES["claude-code"], HARNESSES["codex"]


def executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def harness_install(data: Path, *, status: str = "", sign_in: str = "") -> Path:
    """A pretended set-up of the agent programs: the adapters' entry files and the programs,
    which are small scripts. `status` and `sign_in` are what the programs print."""
    base = data / "engine" / "harness"
    root = base / "0.99.1+2.2.2"
    adapters = {}
    for h in (CLAUDE, CODEX):
        entry = root / "node_modules" / h.package / "dist" / "index.js"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("// the adapter\n")
        adapters[h.id] = str(entry.relative_to(root))
        executable(
            root / "node_modules" / Path(*h.program),
            "#!/bin/sh\n"
            'env > "$HOME/.seen-env"\n'
            f'case "$1 $2" in\n'
            f"  'auth login'|'login ') printf '%s\\n' '{sign_in}'; exec sleep 30 ;;\n"
            f"esac\n"
            f"printf '%s\\n' '{status}'\n",
        )
    (base / "state.json").write_text(
        json.dumps({"schema": 1, "version": "0.99.1+2.2.2", "dir": "0.99.1+2.2.2",
                    "lock_sha256": "0" * 64, "adapters": adapters})
    )  # fmt: skip
    return root


def node_install(data: Path) -> Path:
    base = data / "engine" / "node"
    executable(base / "24.22.3" / "bin" / "node", "#!/bin/sh\n")
    (base / "state.json").write_text(json.dumps({"bin": "24.22.3/bin"}))
    return base / "24.22.3" / "bin"


# ---- names ---------------------------------------------------------------------------------------


def test_a_harness_model_is_named_by_its_harness_and_anything_else_is_wasify_ais():
    known = ("claude-code", "codex")
    assert harness_model("claude-code:opus", known) == ("claude-code", "opus")
    assert harness_model("codex:default", known) == ("codex", "")
    assert harness_model("codex:", known) == ("codex", "")
    # a vendor's model and a local one are Wasify AI's own
    assert harness_model("anthropic:claude-opus-5-5", known) is None
    assert harness_model("this-computer", known) is None
    assert harness_model("", known) is None
    assert harness_of("claude-code:sonnet") == (CLAUDE, "sonnet")
    assert harness_of("gemini-cli:x") is None  # not in this release (ADR-0107, question 3)


# ---- sign-in -------------------------------------------------------------------------------------


def test_of_the_programs_status_only_signed_in_how_and_the_plan_are_kept():
    said = json.dumps({
        "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
        "email": "someone@example.com", "orgId": "org-1", "orgName": "Their org",
        "subscriptionType": "max",
    })  # fmt: skip
    got = read_status(CLAUDE, 0, said)
    assert got == {"signed_in": True, "how": "plan", "plan": "max"}
    assert "example.com" not in json.dumps(got)
    assert read_status(CLAUDE, 0, '{"loggedIn": false}')["signed_in"] is False
    assert read_status(CLAUDE, 1, "not json")["signed_in"] is False
    key = read_status(CLAUDE, 0, '{"loggedIn": true, "authMethod": "api_key"}')
    assert (key["how"], key["plan"]) == ("key", "")

    assert read_status(CODEX, 0, "Logged in using ChatGPT") == {
        "signed_in": True, "how": "plan", "plan": "ChatGPT",
    }  # fmt: skip
    assert read_status(CODEX, 0, "Logged in using an API key - sk-***")["how"] == "key"
    assert read_status(CODEX, 1, "Not logged in")["signed_in"] is False


def test_a_sign_in_page_is_shown_only_when_it_is_the_providers():
    assert page_of(CLAUDE, "Open https://claude.ai/oauth/authorize?code=true&x=1 to sign in") == (
        "https://claude.ai/oauth/authorize?code=true&x=1"
    )
    codex_page = page_of(CODEX, "go to https://auth.openai.com/oauth/authorize?a=b")
    assert codex_page is not None and codex_page.startswith("https://auth.openai.com/")
    assert page_of(CLAUDE, "see https://evil.example/claude.ai") is None
    assert page_of(CODEX, "https://claude.ai/x") is None
    assert page_of(CLAUDE, "no address here") is None


async def test_the_program_signs_in_by_itself_with_the_persons_home_and_none_of_our_env(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    home.mkdir()
    data = tmp_path / "data"
    status = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "a@b.c",
                         "subscriptionType": "pro"})  # fmt: skip
    harness_install(data, status=status, sign_in="Open https://claude.ai/oauth/authorize?x=1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-reach-the-program")
    accounts = HarnessAccounts(data, home=home)
    try:
        got = await accounts.status("claude-code")
        assert got["installed"] and got["signed_in"]
        assert (got["how"], got["plan"]) == ("plan", "pro")
        assert "a@b.c" not in json.dumps(got)
        seen = (home / ".seen-env").read_text()
        assert f"HOME={home}" in seen
        assert "ANTHROPIC_API_KEY" not in seen and "sk-must-not" not in seen

        signing = await accounts.sign_in("claude-code")
        assert signing["signing_in"] is True
        for _ in range(40):
            if (await accounts.status("claude-code"))["page"]:
                break
            await asyncio.sleep(0.05)
        assert (await accounts.status("claude-code"))["page"] == (
            "https://claude.ai/oauth/authorize?x=1"
        )
        await accounts.cancel("claude-code")
        after = await accounts.status("claude-code")
        assert after["signing_in"] is False and after["page"] == ""
    finally:
        await accounts.close()


async def test_a_program_that_is_not_set_up_says_so(tmp_path):
    accounts = HarnessAccounts(tmp_path, home=tmp_path)
    got = await accounts.status("codex")
    assert got["installed"] is False and got["signed_in"] is False
    with pytest.raises(LookupError):
        await accounts.sign_in("codex")


# ---- the install and the command -----------------------------------------------------------------


def test_the_programs_are_found_only_inside_their_own_folder(tmp_path):
    assert find_harness_install(tmp_path) is None
    root = harness_install(tmp_path)
    found = find_harness_install(tmp_path)
    assert found is not None and found.root == root.resolve()
    assert found.adapter(CLAUDE) == root.resolve() / found.adapters["claude-code"]
    state = tmp_path / "engine" / "harness" / "state.json"
    raw = json.loads(state.read_text())
    raw["adapters"]["codex"] = "../../../../outside.js"
    state.write_text(json.dumps(raw))
    assert find_harness_install(tmp_path) is None


def test_the_program_is_started_with_the_persons_home_and_its_own_settings_only(tmp_path):
    harness_install(tmp_path)
    found = find_harness_install(tmp_path)
    assert found is not None
    command = acp_command(CLAUDE, found, Path("/n/node"), tmp_path / "tmp", Path("/Users/p"))
    assert command[0] == "/usr/bin/env"
    assert command[1] == "HOME=/Users/p"
    assert f"CLAUDE_CODE_TMPDIR={tmp_path / 'tmp'}" in command
    assert "DISABLE_AUTOUPDATER=1" in command
    assert command[-2:] == ["/n/node", str(found.adapter(CLAUDE))]
    assert not any("KEY" in part or "TOKEN" in part for part in command)
    codex = acp_command(CODEX, found, Path("/n/node"), tmp_path, Path("/Users/p"))
    assert codex == ["/usr/bin/env", "HOME=/Users/p", "/n/node", str(found.adapter(CODEX))]


# ---- the proxy -----------------------------------------------------------------------------------


def _basic(proxy: InstallProxy, who: str) -> dict[str, str]:
    password = proxy.url_for(who).split("//", 1)[1].split("@", 1)[0].split(":", 1)[1]
    raw = base64.b64encode(f"{who}:{password}".encode()).decode()
    return {"proxy-authorization": f"Basic {raw}"}


def test_a_harness_reaches_its_own_provider_and_nothing_else():
    proxy = InstallProxy(
        ["pypi.org"], harness_hosts={"claude-code": CLAUDE.hosts, "codex": CODEX.hosts}
    )
    claude, codex = _basic(proxy, "claude-code"), _basic(proxy, "codex")
    assert proxy._judge("CONNECT", "api.anthropic.com:443", claude)[0] == 200
    assert proxy._judge("CONNECT", "mcp-proxy.anthropic.com:443", claude)[0] == 200
    assert proxy._judge("CONNECT", "anthropic.com:443", claude)[0] == 200
    assert proxy._judge("CONNECT", "chatgpt.com:443", codex)[0] == 200
    # not another's provider, not a package index, not a look-alike, not another port
    assert proxy._judge("CONNECT", "chatgpt.com:443", claude)[:2] == (403, "not_the_provider")
    assert proxy._judge("CONNECT", "pypi.org:443", claude)[:2] == (403, "not_the_provider")
    assert proxy._judge("CONNECT", "evilanthropic.com:443", claude)[0] == 403
    assert proxy._judge("CONNECT", "http-intake.logs.us5.datadoghq.com:443", claude)[0] == 403
    assert proxy._judge("CONNECT", "api.anthropic.com:80", claude)[:2] == (403, "port")
    # the agent's commands and the person's terminal never reach a provider
    proxy.open_for_agent()
    assert proxy._judge("CONNECT", "api.anthropic.com:443", _basic(proxy, AGENT))[0] == 403
    assert proxy._judge("CONNECT", "chatgpt.com:443", _basic(proxy, PERSON))[0] == 403
    # one harness's password is not another's
    wrong = {"proxy-authorization": codex["proxy-authorization"].replace("Y29kZXg", "Y2xh")}
    assert proxy._judge("CONNECT", "api.anthropic.com:443", wrong)[0] == 407
    assert "harness_hosts" in proxy.state()
    assert "token" not in json.dumps(proxy.state()).lower()


# ---- the profile ---------------------------------------------------------------------------------


def test_files_beside_a_folder_are_opened_by_how_their_path_begins():
    filled = fill_profile(
        "(allow file-write*\n{{WRITE}})\n(allow file-read*\n{{OPEN}})\n{{NO_WRITE}}\n"
        "(deny file-read*\n{{CLOSED}})\n(allow file-read-metadata\n{{WAY}})",
        write=[Path("/Users/p/.claude")],
        read_only=[],
        closed=[Path("/Users")],
        write_starting=[Path("/Users/p/.claude.json.")],
    )
    assert filled.count('(regex #"^/Users/p/\\.claude\\.json\\.")') == 2  # written and read
    with pytest.raises(CodingError):
        fill_profile("{{WRITE}}{{OPEN}}{{CLOSED}}{{WAY}}{{NO_WRITE}}", write=[], read_only=[],
                     closed=[], write_starting=[Path('/a"b')])  # fmt: skip


async def test_a_harness_server_opens_its_programs_sign_in_and_the_wasify_server_none(tmp_path):
    data, home = tmp_path / "data", tmp_path / "home"
    home.mkdir()
    install(data)
    root = harness_install(data)
    node_install(data)
    proxy = InstallProxy(["pypi.org"], harness_hosts={"claude-code": CLAUDE.hosts})
    main = server(data, proxy=proxy, home=home)
    try:
        with pytest.raises(CodingError):
            main.for_harness("gemini-cli")
        child = main.for_harness("claude-code")
        assert main.for_harness("claude-code") is child
        assert child.run_dir == data / "coding" / "harness" / "claude-code"
        await child.ensure_running()
        await main.ensure_running()
        theirs = (child.run_dir / "engine.sb").read_text()
        ours = (main.run_dir / "engine.sb").read_text()
        h = real(home)
        for opened in (f'"{h}/.claude"', f'"{h}/.claude.json"', f'"{h}/Library/Keychains"',
                       f'"{real(root)}"'):  # fmt: skip
            assert opened in theirs
            assert opened not in ours
        assert "\\.claude\\.json\\." in theirs and "claude" not in ours.replace("claude-501", "")
        env = (await child.request("GET", "/fake/env")).json()["env"]
        assert "claude-code:" in env.get("HTTPS_PROXY", "")
        mine = (await main.request("GET", "/fake/env")).json()["env"]
        assert "agent:" in mine.get("HTTPS_PROXY", "")
        assert main.state()["harnesses"] == {"claude-code": True}
        command = child.acp_command()
        assert command[1] == f"HOME={h}"
        assert await main.stop() is True
        assert not child.running and not main.running
    finally:
        await main.close()


async def test_a_harness_that_is_not_set_up_says_so(tmp_path):
    install(tmp_path)
    main = server(tmp_path)
    try:
        with pytest.raises(CodingError) as raised:
            main.for_harness("codex").acp_command()
        assert raised.value.code == "harness_not_installed"
    finally:
        await main.close()


# ---- the events ----------------------------------------------------------------------------------


def _events(name: str) -> list[dict]:
    return [item["event"] for item in json.loads((FIXTURES / f"{name}.json").read_text())["events"]]


def test_a_programs_steps_are_said_in_our_words_and_its_use_is_given_once():
    reader = Reader()
    out = [pair for event in _events("acp-codex") for pair in reader.read(event)]
    kinds = [k for k, _ in out]
    steps = [d for k, d in out if k == places.STEP]
    results = [d for k, d in out if k == places.RESULT]
    assert kinds[0] == places.STATE
    assert {s["tool"] for s in steps} == {"terminal", "file_editor"}
    assert any(s.get("command") == "python3 -m pytest -q" for s in steps)
    edit = next(s for s in steps if s["tool"] == "file_editor")
    assert edit["path"].endswith("calc.py") and edit["command"] == "edit"
    assert len(results) == len(steps)  # each step answered once
    assert [r["ok"] for r in results].count(False) == 2  # git status and pytest failed there
    assert any(k == places.TEXT and "average" in d["text"] for k, d in out)
    assert reader.status == "finished" and reader.over
    assert reader.end()["why"] == places.FINISHED
    used = reader.take_usage()
    assert used == {"usd": 0.063708, "tokens_in": 148478, "tokens_out": 1128,
                    "model": "gpt-5.6-terra"}  # fmt: skip
    assert reader.take_usage() is None  # given once


def test_claudes_pending_steps_are_said_once_and_answered():
    reader = Reader()
    out = [pair for event in _events("acp-claude") for pair in reader.read(event)]
    steps = [d for k, d in out if k == places.STEP]
    results = [d for k, d in out if k == places.RESULT]
    assert len(steps) == 3 and len(results) == 3
    assert all(r["ok"] for r in results)
    used = reader.take_usage()
    assert used is not None and used["usd"] > 0 and used["model"] == ""


# ---- a session on the fake Agent Server ----------------------------------------------------------


class NoGateway:
    """A harness session asks nothing of the gateway: every call fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f"the gateway was asked for {name}")


async def _turn(place: ThisComputer, session: str, text: str) -> list:
    opened = asyncio.Event()
    stream = place.follow(session, opened=opened)
    first = asyncio.ensure_future(anext(stream))
    seen = []
    try:
        await asyncio.wait_for(opened.wait(), 10)
        await place.send(session, text)
        event = await asyncio.wait_for(first, 10)
        while True:
            seen.append(event)
            if event.kind == places.ENDED:
                return seen
            event = await asyncio.wait_for(anext(stream), 10)
    finally:
        first.cancel()
        await stream.aclose()


async def test_a_session_on_a_harness_is_the_programs_own_with_no_token_of_ours(tmp_path):
    data, home, project = tmp_path / "data", tmp_path / "home", tmp_path / "project"
    for folder in (home, project):
        folder.mkdir()
    install(data)
    harness_install(data)
    node_install(data)
    main = server(data, home=home)
    calls: list = []

    async def on_call(call):
        calls.append(call)

    place = ThisComputer(main, NoGateway(), on_call=on_call)
    try:
        account = places.Account("t", "p", "u", "s1")
        spec = SessionSpec(project, model="codex:gpt-5.6-terra", read_only=True, account=account)
        made = await place.start(spec)
        child = main.harness_servers["codex"]
        assert not main.running and child.running  # the Wasify engine's server is not started
        assert real(project) in child.read_only
        asked = (await child.request("GET", f"/fake/conversations/{made}")).json()
        settings = asked["agent_settings"]
        assert settings["agent_kind"] == "acp" and settings["acp_server"] == "codex"
        assert settings["acp_model"] == "gpt-5.6-terra"
        assert settings["acp_command"][:2] == ["/usr/bin/env", f"HOME={real(home)}"]
        assert "llm" not in settings and "security_analyzer" not in asked
        assert "acp_session_mode" not in settings  # Codex has no plan mode of its own here
        sent: list[dict] = []
        real_request = child.request

        async def spy(method, path, **more):
            if path.endswith("/events") and "json" in more:
                sent.append(more["json"])
            return await real_request(method, path, **more)

        child.request = spy
        seen = await _turn(place, made, "Fix the empty list. #replay:acp-codex")
        assert seen[-1].data["why"] == places.FINISHED
        assert any(e.kind == places.STEP and e.data["tool"] == "terminal" for e in seen)
        assert sent[0]["content"][0]["text"].startswith(HARNESS_READ_ONLY_NOTE)
        await asyncio.sleep(0.05)
        assert len(calls) == 1
        assert (calls[0].session_id, calls[0].usd, calls[0].harness) == ("s1", 0.063708, "codex")
        assert place.adopt(made, spec) is True
        await place.end(made)
        assert place.adopt(made, spec) is False  # not taken up again: a new one is started
    finally:
        await place.close()
        await main.close()


async def test_a_claude_session_that_only_reads_plans_first(tmp_path):
    data, home, project = tmp_path / "data", tmp_path / "home", tmp_path / "project"
    for folder in (home, project):
        folder.mkdir()
    install(data)
    harness_install(data)
    node_install(data)
    main = server(data, home=home)
    place = ThisComputer(main, NoGateway(), known=lambda: [])
    try:
        made = await place.start(SessionSpec(project, model="claude-code:default", read_only=True))
        child = main.harness_servers["claude-code"]
        settings = (await child.request("GET", f"/fake/conversations/{made}")).json()[
            "agent_settings"
        ]
        assert settings["acp_session_mode"] == "plan" and "acp_model" not in settings
        writing = await place.start(SessionSpec(project, model="claude-code:opus"))
        assert real(project) in child.workspaces
        settings = (await child.request("GET", f"/fake/conversations/{writing}")).json()[
            "agent_settings"
        ]
        assert "acp_session_mode" not in settings
    finally:
        await place.close()
        await main.close()
