"""A question put to a notebook: the graph on a scripted model and a real store."""

from typing import Any

import pytest
import yaml
from langgraph.checkpoint.memory import InMemorySaver
from notebooks_rig import SPEC, FakeComponents, FakeReader
from wasifyai_notebooks.graph import build_notebook_chat_graph, title_from
from wasifyai_notebooks.ingest import IngestWorker, ingest_one, original_path
from wasifyai_notebooks.routes import Runtime
from wasifyai_notebooks.store import NotebookStore
from wasifyai_platform_sdk import (
    InMemoryUsageRecorder,
    ProviderDeps,
    RunContext,
    RunError,
    build_capabilities,
    load_product_config,
    reset_context,
    set_context,
)

CTX = RunContext("t1", "wasifyai-notebooks", "u1", run_id="r1", thread_id="th1")


@pytest.fixture
def ctx():
    token = set_context(CTX)
    yield CTX
    reset_context(token)


class Rig:
    def __init__(self, tmp_path, turns, *, embedder_ready=True, facts=None, replies=None):
        d = tmp_path / "products" / "wasifyai-notebooks"
        d.mkdir(parents=True)
        (d / "product.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "wasifyai-notebooks",
                    "capabilities": {
                        "text.chat": {
                            "provider": "fake",
                            "defaults": {
                                "turns": turns,
                                **({"replies": replies} if replies else {}),
                            },
                        }
                    },
                }
            )
        )
        self.usage = InMemoryUsageRecorder()
        config = load_product_config(tmp_path / "products", "wasifyai-notebooks")
        self.caps = build_capabilities(
            config, ProviderDeps(products_dir=tmp_path / "products", usage=self.usage)
        )
        self.store = NotebookStore(tmp_path / "nb", dimension=SPEC.dimension, embedder_id=SPEC.id)
        self.components = FakeComponents(tmp_path, embedder_ready=embedder_ready)
        files = tmp_path / "nb" / "files"
        files.mkdir()
        self.reader = FakeReader()
        self.files = files
        worker = IngestWorker(
            self.store, self.components, self.reader, files, tokenizer_factory=lambda: "word"
        )
        self.runtime = Runtime(self.store, self.components, worker, files, tmp_path / "nb" / "tmp")
        self.nb = self.store.create_notebook("t1", "u1", "Notebook")
        self.graph = build_notebook_chat_graph(
            self.caps, InMemorySaver(), lambda: self.runtime, facts or (lambda: (8192, "capable"))
        )
        self._n = 0

    @property
    def model(self) -> Any:  # the scripted provider keeps what it was sent in `chats`
        _binding, provider = self.caps.text._bound["chat"]
        return provider

    async def add(self, name, text, suffix=".txt"):
        doc, _ = self.store.add_file(
            "t1", "u1", self.nb["id"], title=name, suffix=suffix, mime="text/plain",
            size_bytes=len(text), sha256=name,
        )  # fmt: skip
        path = original_path(self.files, self.nb["id"], doc)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        await ingest_one(
            self.store,
            self.components,
            self.reader,
            self.files,
            doc,
            tokenizer_factory=lambda: "word",
        )
        return doc

    async def ask(
        self, text, conversation_id=None, document_ids=None, notebook_id=None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        graph_input: dict[str, Any] = {"text": text, "notebook_id": notebook_id or self.nb["id"]}
        if conversation_id:
            graph_input["conversation_id"] = conversation_id
        if document_ids is not None:
            graph_input["document_ids"] = document_ids
        config = {"configurable": {"thread_id": f"th-{self._n}"}}
        self._n += 1
        final: dict[str, Any] = {}
        events: list[dict[str, Any]] = []
        graph: Any = self.graph
        async for mode, chunk in graph.astream(
            graph_input, config, stream_mode=["custom", "values"]
        ):
            if mode == "custom":
                events.append(chunk)
            else:
                final = chunk
        return final, events


BUDGET = "# Budget\n\nThe marketing budget for the launch is $350,000.\n"
PEOPLE = "# People\n\nEngineering has 48 people and 5 open roles.\n"


async def test_a_question_is_searched_answered_cited_and_saved(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "The marketing budget for the launch is $350,000 [1]."}])
    await rig.add("budget.txt", BUDGET)
    await rig.add("hr.txt", PEOPLE)
    state, events = await rig.ask("What is the marketing budget?")
    assert state["status"] == "done"
    assert state["reply"] == "The marketing budget for the launch is $350,000 [1]."
    (cite,) = state["citations"]
    assert cite["n"] == 1 and cite["title"] == "budget.txt" and "$350,000" in cite["text"]
    assert state["searched"] == 2 and state["title"] == "What is the marketing budget?"

    # the search is shown as a step, then the answer streams
    kinds = [e["type"] for e in events]
    assert kinds.index("tool_call") < kinds.index("tool_result") < kinds.index("token")
    result = next(e for e in events if e["type"] == "tool_result")
    assert (
        result["name"] == "search_sources" and result["output"]["hits"][0]["title"] == "budget.txt"
    )

    # the model was given the passages with the question, under the fuller prompt
    sent = rig.model.chats[0]["messages"]
    assert sent[0]["role"] == "system" and sent[0]["content"].startswith("Answer the question")
    assert "[1] # Budget" in sent[-1]["content"]
    assert sent[-1]["content"].endswith("Question: What is the marketing budget?")

    # saved: the question and the answer with its citations
    msgs = rig.store.messages("t1", "u1", rig.nb["id"], state["conversation_id"])
    assert [(m["role"], m["text"]) for m in msgs] == [
        ("user", "What is the marketing budget?"),
        ("assistant", "The marketing budget for the launch is $350,000 [1]."),
    ]
    assert msgs[1]["citations"][0]["title"] == "budget.txt"
    assert [e.kind for e in rig.usage.events if e.kind == "notebooks.message"] == [
        "notebooks.message"
    ]


async def test_the_next_question_continues_with_the_history_without_old_passages(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "It is $350,000 [1]."}, {"text": "Forty-eight people [1]."}])
    await rig.add("budget.txt", BUDGET)
    await rig.add("hr.txt", PEOPLE)
    first, _ = await rig.ask("What is the marketing budget?")
    second, _ = await rig.ask("How many people work in engineering?", first["conversation_id"])
    assert second["conversation_id"] == first["conversation_id"]
    assert second["title"] == "What is the marketing budget?"  # the first question, kept
    sent = rig.model.chats[1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "What is the marketing budget?"  # earlier question: text only
    assert "<retrieved_context>" not in sent[1]["content"]
    assert "<retrieved_context>" in sent[-1]["content"]


async def test_refusal_hygiene_labels_come_off_a_sentence_that_says_it_was_not_found(tmp_path, ctx):
    rig = Rig(
        tmp_path,
        [{"text": "The document does not mention the chief financial officer [1]."}],
    )
    await rig.add("budget.txt", BUDGET)
    state, _ = await rig.ask("Who is the chief financial officer?")
    assert state["reply"] == "The document does not mention the chief financial officer."
    assert state["citations"] == [] and state["labels_removed"] == 1


async def test_a_scope_limits_what_is_searched(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "Only the people file [1]."}])
    a = await rig.add("budget.txt", BUDGET)
    b = await rig.add("hr.txt", PEOPLE)
    state, _ = await rig.ask("people and budget", document_ids=[b["id"]])
    assert state["searched"] == 1 and state["citations"][0]["title"] == "hr.txt"
    sent = rig.model.chats[0]["messages"][-1]["content"]
    assert "budget.txt" not in sent
    assert a["id"] != b["id"]


async def test_nothing_to_ask_is_refused_in_words(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "x"}])
    state, _ = await rig.ask("anything?")
    assert state["status"] == "refused" and state["refusal"]["code"] == "no_sources"
    doc, _ = rig.store.add_file(
        "t1", "u1", rig.nb["id"], title="a.txt", suffix=".txt", mime="x", size_bytes=1, sha256="s"
    )  # still pending: not read yet
    state, _ = await rig.ask("anything?")
    assert state["refusal"]["code"] == "sources_reading"
    state, _ = await rig.ask("   ")
    assert state["refusal"]["code"] == "invalid_request"
    state, _ = await rig.ask("x" * 5000)
    assert state["status"] == "refused"
    state, _ = await rig.ask("hi", notebook_id="nope")
    assert state["refusal"]["code"] == "not_found"
    assert doc["id"] and rig.model.chats == []  # the model was never asked


async def test_another_persons_notebook_or_conversation_is_not_found(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "ok"}])
    await rig.add("budget.txt", BUDGET)
    other = rig.store.create_notebook("t1", "u2", "Theirs")
    state, _ = await rig.ask("hi", notebook_id=other["id"])
    assert state["refusal"]["code"] == "not_found"
    state, _ = await rig.ask("hi", conversation_id="not-a-conversation")
    assert state["refusal"]["code"] == "not_found"


async def test_without_the_search_model_the_run_errors_with_a_code(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "x"}], embedder_ready=False)
    # a source can be ready only if the model was there when it was read: mark one by hand
    doc, _ = rig.store.add_file(
        "t1", "u1", rig.nb["id"], title="a.txt", suffix=".txt", mime="x", size_bytes=1, sha256="s"
    )
    rig.store.begin(doc["id"])
    from wasifyai_notebooks.chunking import Passage

    rig.store.finish(
        doc["id"], markdown="a", pages=None, passages=[Passage("a", 1, 1)],
        vectors=[[0.0] * SPEC.dimension], embedder=SPEC.id,
    )  # fmt: skip
    with pytest.raises(RunError) as e:
        await rig.ask("anything?")
    assert e.value.code == "embedder_missing"


async def test_a_model_that_fails_ends_the_run_with_a_retryable_error(tmp_path, ctx):
    rig = Rig(tmp_path, [{"text": "x"}])
    await rig.add("budget.txt", BUDGET)

    async def broken(*a, **k):
        raise ConnectionError("down")
        yield  # pragma: no cover

    rig.model.chat = broken
    with pytest.raises(RunError) as e:
        await rig.ask("What is the budget?")
    assert e.value.code == "language_failed" and e.value.retryable


def test_a_title_is_the_first_question_cut_short():
    assert title_from("  What   is\nthe budget? ") == "What is the budget?"
    assert len(title_from("x" * 200)) == 60
