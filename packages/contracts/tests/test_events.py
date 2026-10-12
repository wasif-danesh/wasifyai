import json
from uuid import uuid4

from pydantic import TypeAdapter
from wasifyai_contracts import DoneEvent, SseEvent, TokenEvent, format_sse

RUN_ID, THREAD_ID = uuid4(), uuid4()


def test_format_sse_envelope():
    msg = format_sse(TokenEvent(seq=2, node="hello", text="hi", run_id=RUN_ID, thread_id=THREAD_ID))
    head, data = msg.strip().split("\n", 2)[0:2], msg.split("data: ")[1]
    assert head == ["id: 2", "event: token"]
    body = json.loads(data)
    assert body["text"] == "hi" and body["seq"] == 2 and "event" not in body


def test_discriminated_union_roundtrip():
    ev = DoneEvent(seq=3, outputs={"reply": "x"}, run_id=RUN_ID, thread_id=THREAD_ID)
    parsed = TypeAdapter(SseEvent).validate_python(ev.model_dump(mode="json"))
    assert isinstance(parsed, DoneEvent)
