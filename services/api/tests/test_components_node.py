"""Node for coding projects on the one installer (stage C4): four steps, the folder the sandbox is
given, and the refusals. The download is served by a fake transport; "node" is a small script."""

import hashlib
import io
import tarfile
from pathlib import Path

import httpx
import pytest
from wasifyai_api.components.manifest import Manifest, Pins, load_manifest
from wasifyai_api.components.node import NodeComponent, find_node
from wasifyai_platform_sdk.installer import Archive, InstallError

URL = "https://example.test/node-v9.9.9-darwin-arm64.tar.gz"
NODE_OK = "#!/bin/sh\necho v9.9.9\n"


def archive(node: str | None = NODE_OK) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        files = {"node-v9.9.9/README.md": b"node", "node-v9.9.9/bin/npm": b"#!/bin/sh\necho 11\n"}
        if node is not None:
            files["node-v9.9.9/bin/node"] = node.encode()
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def component(tmp_path: Path, body: bytes, sha: str | None = None) -> NodeComponent:
    pin = Archive(URL, len(body), sha or hashlib.sha256(body).hexdigest(), "tar.gz", strip=1)
    pins = Pins("node", "Node for coding projects", "9.9.9", "nodejs.org", 1000, pin, {})
    manifest = Manifest("darwin-arm64", "3.12.15", {"node": pins})

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == URL
        return httpx.Response(200, content=body)

    client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: E731
    return NodeComponent(tmp_path, manifest, client=client)


async def test_it_installs_in_four_steps_and_the_sandbox_is_given_its_folder(tmp_path):
    body = archive()
    c = component(tmp_path, body)
    assert c.status() == {"state": "not_installed", "needs_bytes": len(body)}
    assert find_node(tmp_path) is None
    c.install(len(body))
    await c.wait()
    assert c.status()["state"] == "installed" and c.status()["version"] == "9.9.9"
    folder = find_node(tmp_path)
    assert folder is not None
    assert folder == (tmp_path / "engine" / "node" / "9.9.9" / "bin").resolve()
    assert (folder / "node").is_file() and (folder / "npm").is_file()
    assert not (tmp_path / "engine" / "node" / "downloads").exists()
    with pytest.raises(InstallError):
        c.install(len(body))  # it is there already
    assert c.uninstall() > 0 and find_node(tmp_path) is None
    assert c.status()["state"] == "not_installed"


async def test_a_wrong_download_a_node_that_does_not_start_and_a_stale_size_are_refused(tmp_path):
    body = archive()
    wrong = component(tmp_path / "a", body, sha="0" * 64)
    wrong.install(len(body))
    await wrong.wait()
    assert wrong.status()["state"] == "failed" and find_node(tmp_path / "a") is None
    other = archive("#!/bin/sh\necho v1.0.0\n")  # not the pinned version
    c = component(tmp_path / "b", other)
    c.install(len(other))
    await c.wait()
    assert c.status()["state"] == "failed" and find_node(tmp_path / "b") is None
    with pytest.raises(InstallError):
        component(tmp_path / "c", body).install(len(body) + 1)


def test_a_state_file_that_points_outside_its_folder_is_not_believed(tmp_path):
    root = tmp_path / "engine" / "node"
    root.mkdir(parents=True)
    (tmp_path / "elsewhere" / "bin").mkdir(parents=True)
    (tmp_path / "elsewhere" / "bin" / "node").write_text("x")
    (root / "state.json").write_text('{"schema": 1, "version": "9", "bin": "../../elsewhere/bin"}')
    assert find_node(tmp_path) is None


def test_where_it_is_offered():
    assert NodeComponent(Path("/nowhere"), Manifest("haiku-x64", "", {})).status()["state"] == (
        "unsupported"
    )
    pins = load_manifest("darwin-arm64").get("node")
    assert pins is not None and pins.archive is not None
    assert pins.archive.url.startswith("https://nodejs.org/dist/v")
    assert len(pins.archive.sha256) == 64
    assert f"v{pins.version}" in pins.archive.url
