"""The install proxy (stage C3): which requests from inside the coding sandbox it lets through.
Everything here is on loopback; the "package index" is a small echo server."""

import asyncio
import base64

import pytest
from wasifyai_api.coding_proxy import AGENT, PERSON, InstallProxy, read_hosts


async def ask(proxy: InstallProxy, target: str, who: str | None, *, method: str = "CONNECT"):
    """One request to the proxy: its status line, and the open connection when let through."""
    host, port = proxy.address.split(":")
    reader, writer = await asyncio.open_connection(host, int(port))
    head = f"{method} {target} HTTP/1.1\r\nHost: {target}\r\n"
    if who is not None:
        url = proxy.url_for(who) if who in (AGENT, PERSON) else f"http://{who}@x"
        pair = url.split("//", 1)[1].rsplit("@", 1)[0]
        head += f"Proxy-Authorization: Basic {base64.b64encode(pair.encode()).decode()}\r\n"
    writer.write((head + "\r\n").encode())
    await writer.drain()
    status = (await asyncio.wait_for(reader.readline(), 5)).decode().strip()
    return status, reader, writer


@pytest.fixture
async def index():
    """A server that says back what it is sent: stands for a package index."""

    async def echo(reader, writer):
        while data := await reader.read(1024):
            writer.write(b"echo:" + data)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()


@pytest.fixture
async def proxy(index):
    made = InstallProxy(["127.0.0.1"], port=index)
    await made.start()
    yield made
    await made.close()


def test_the_list_holds_package_indexes_only():
    hosts = read_hosts()
    assert "pypi.org" in hosts and "registry.npmjs.org" in hosts and "crates.io" in hosts
    assert not any("github" in h or "*" in h or "/" in h for h in hosts)


async def test_the_person_is_let_through_to_a_host_on_the_list(proxy):
    status, reader, writer = await ask(proxy, f"127.0.0.1:{proxy.port}", PERSON)
    assert status.split()[1] == "200"
    await reader.readline()  # the empty line after the status
    writer.write(b"hello")
    await writer.drain()
    assert await asyncio.wait_for(reader.read(100), 5) == b"echo:hello"
    writer.close()
    assert proxy.let_through == 1 and proxy.seen[-1]["ok"] is True


async def test_the_agent_is_let_through_only_while_an_install_is_allowed(proxy):
    target = f"127.0.0.1:{proxy.port}"
    status, _, writer = await ask(proxy, target, AGENT)
    writer.close()
    assert status.split()[1] == "403" and proxy.seen[-1]["why"] == "no_install_allowed"
    proxy.open_for_agent()
    status, _, writer = await ask(proxy, target, AGENT)
    writer.close()
    assert status.split()[1] == "200"
    proxy.close_for_agent()
    status, _, writer = await ask(proxy, target, AGENT)
    writer.close()
    assert status.split()[1] == "403"
    proxy.open_for_agent(0.05)
    await asyncio.sleep(0.1)
    assert not proxy.open_to_agent


@pytest.mark.parametrize(
    ("target", "who", "method", "status", "why"),
    [
        ("example.com:{port}", PERSON, "CONNECT", "403", "not_on_the_list"),
        ("127.0.0.1:22", PERSON, "CONNECT", "403", "port"),
        ("127.0.0.1:{port}", None, "CONNECT", "407", "who"),
        ("127.0.0.1:{port}", "person:wrong", "CONNECT", "407", "who"),
        ("127.0.0.1:{port}", "nobody:x", "CONNECT", "407", "who"),
        ("http://127.0.0.1:{port}/simple/", PERSON, "GET", "405", "only_https"),
    ],
)
async def test_everything_else_is_refused(proxy, target, who, method, status, why):
    proxy.open_for_agent()
    got, _, writer = await ask(proxy, target.format(port=proxy.port), who, method=method)
    writer.close()
    assert got.split()[1] == status and proxy.seen[-1]["why"] == why
    assert proxy.let_through == 0 and proxy.refused == 1


async def test_what_it_says_of_itself_holds_no_password(proxy):
    said = str(proxy.state()) + str(list(proxy.seen))
    for who in (AGENT, PERSON):
        password = proxy.url_for(who).split(":")[2].split("@")[0]
        assert len(password) > 20 and password not in said
    assert proxy.url_for(AGENT) != proxy.url_for(PERSON)
