"""A fake ComfyUI that speaks the real HTTP + WebSocket protocol, for deterministic tests.

Graph behaviour is driven by class types in the submitted workflow:
  "Invalid" -> POST /prompt answers 400 (validation failure)
  "Boom"    -> execution fails with an `execution_error` message
  "Slow"    -> never finishes (to test timeouts)
"""

import asyncio
import json
import threading
import time
from uuid import uuid4

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"
WAV = b"RIFFfake-wav-bytes"


class FakeComfy:
    def __init__(self) -> None:
        self.sockets: dict[str, WebSocket] = {}
        self.history: dict[str, dict] = {}
        self.submitted: list[dict] = []
        self.uploads: list[tuple[str, bytes]] = []  # (content type, raw multipart body)
        self.freed = 0
        self.interrupted = 0
        self.app = Starlette(
            routes=[
                Route("/prompt", self.prompt, methods=["POST"]),
                Route("/history/{pid}", self.get_history),
                Route("/view", self.view),
                Route("/upload/image", self.upload, methods=["POST"]),
                Route("/free", self.free, methods=["POST"]),
                Route("/interrupt", self.interrupt, methods=["POST"]),
                WebSocketRoute("/ws", self.ws),
            ]
        )

    async def ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        cid = websocket.query_params.get("clientId", "")
        self.sockets[cid] = websocket
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            self.sockets.pop(cid, None)

    async def prompt(self, request: Request) -> Response:
        body = await request.json()
        graph = body["prompt"]
        self.submitted.append(body)
        if any(n.get("class_type") == "Invalid" for n in graph.values()):
            return JSONResponse(
                {
                    "error": {"message": "Prompt outputs failed validation"},
                    "node_errors": {"1": {"secret": "internal path /srv/x"}},
                },
                status_code=400,
            )
        pid = str(uuid4())
        asyncio.create_task(self._execute(body.get("client_id", ""), pid, graph))
        return JSONResponse({"prompt_id": pid, "number": 1})

    async def _send(self, cid: str, msg: dict) -> None:
        if ws := self.sockets.get(cid):
            await ws.send_text(json.dumps(msg))

    async def _execute(self, cid: str, pid: str, graph: dict) -> None:
        kinds = {n.get("class_type") for n in graph.values()}
        await asyncio.sleep(0.05)
        await self._send(
            cid, {"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 1}}}}
        )
        # noise a real server sends: another client's prompt, and a binary preview frame
        await self._send(
            cid, {"type": "progress", "data": {"value": 1, "max": 2, "prompt_id": "someone-else"}}
        )
        if ws := self.sockets.get(cid):
            await ws.send_bytes(b"\x00\x00\x00\x01preview")
        if "Slow" in kinds:
            return
        for i in range(1, 5):
            await asyncio.sleep(0.02)
            await self._send(
                cid,
                {"type": "progress", "data": {"value": i, "max": 4, "prompt_id": pid, "node": "8"}},
            )
        if "Boom" in kinds:
            self.history[pid] = {"status": {"status_str": "error"}, "outputs": {}}
            await self._send(
                cid,
                {
                    "type": "execution_error",
                    "data": {
                        "prompt_id": pid,
                        "exception_message": "CUDA out of memory at /srv/secret/path",
                    },
                },
            )
            return
        outputs = {}
        for node_id, node in graph.items():
            if node.get("class_type") == "SaveImage":
                outputs[node_id] = {
                    "images": [
                        {"filename": f"out_{node_id}.png", "subfolder": "", "type": "output"}
                    ]
                }
            if node.get("class_type") == "SaveAudio":
                outputs[node_id] = {
                    "audio": [{"filename": f"out_{node_id}.wav", "subfolder": "", "type": "output"}]
                }
        self.history[pid] = {"status": {"status_str": "success"}, "outputs": outputs}
        await self._send(cid, {"type": "executing", "data": {"node": None, "prompt_id": pid}})

    async def get_history(self, request: Request) -> Response:
        pid = request.path_params["pid"]
        return JSONResponse({pid: self.history[pid]} if pid in self.history else {})

    async def view(self, request: Request) -> Response:
        name = request.query_params["filename"]
        return Response(
            WAV if name.endswith(".wav") else PNG, media_type="application/octet-stream"
        )

    async def upload(self, request: Request) -> Response:
        self.uploads.append((request.headers.get("content-type", ""), await request.body()))
        return JSONResponse({"name": "wasifyai-uploaded.png", "subfolder": "", "type": "temp"})

    async def free(self, request: Request) -> Response:
        self.freed += 1
        return JSONResponse({})

    async def interrupt(self, request: Request) -> Response:
        self.interrupted += 1
        return JSONResponse({})


class FakeComfyServer:
    """Runs FakeComfy on a free port in a background thread."""

    def __init__(self) -> None:
        self.fake = FakeComfy()
        self.config = uvicorn.Config(self.fake.app, host="127.0.0.1", port=0, log_level="warning")
        self.server = uvicorn.Server(self.config)
        self._thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> str:
        self._thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("fake ComfyUI did not start")
            time.sleep(0.02)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        self.server.should_exit = True
        self._thread.join(timeout=5)
