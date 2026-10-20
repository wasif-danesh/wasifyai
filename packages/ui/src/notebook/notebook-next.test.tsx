// @vitest-environment jsdom
// The notebook chat on assistant-ui (ADR-0082, stage CU4): the behaviours of the old `NotebookChat` (notebook.test.tsx) run against
// the new screen, and what is new: a model's thinking, the markdown rules, and the Labs switch in the workspace.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  AskState,
  AskedMessage,
  NotebookConversation,
  NotebookSource,
  NotebooksApi,
  OnEvent,
  ParsedEvent,
} from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CHAT_NEXT_KEY } from "../chat/labs";
import { ADVERSARIAL } from "../chat/thread/markdown/adversarial";
import type { NotebookChatProps } from "./NotebookChat";
import { NotebookChatNext } from "./NotebookChatNext";
import { NotebookWorkspace } from "./NotebookWorkspace";

const citation = {
  n: 1,
  chunk_id: 7,
  document_id: "s1",
  title: "budget.pdf",
  start_line: 3,
  end_line: 4,
  text: "The marketing budget is $350,000.",
};

const idle: AskState = {
  conversationId: "c1",
  title: "",
  phase: "idle",
  error: null,
  runId: null,
  lastSeq: 0,
  messages: [],
};

const ask = (text: string): AskedMessage => ({ id: "u", role: "user", text, citations: [] });
const answer = (over: Partial<AskedMessage> = {}): AskedMessage => ({
  id: "a",
  role: "assistant",
  text: "It is $350,000 [1], plus tax [7].",
  citations: [citation],
  ...over,
});

function chat(over: Partial<NotebookChatProps> = {}) {
  const props: NotebookChatProps = {
    state: { ...idle, messages: [ask("What is the budget?"), answer()] },
    onSend: vi.fn(),
    onStop: vi.fn(),
    onRetry: vi.fn(),
    onOpenCitation: vi.fn(),
    scope: "2 of 3 sources",
    ...over,
  };
  return { props, ...render(<NotebookChatNext {...props} />) };
}

/** streamdown loads on demand; until it has, the text is shown as it is. */
const formatted = (c: HTMLElement) =>
  waitFor(() => expect(c.querySelector("[data-markdown]")).not.toBeNull());

afterEach(() => localStorage.clear());

describe("answers with citations", () => {
  it("renders a label as a button that opens its passage, and leaves unknown ones as text", async () => {
    const { props, container } = chat({
      state: {
        ...idle,
        messages: [ask("What is the budget?"), answer({ searched: { sources: 2, passages: 3 } })],
      },
    });
    await formatted(container);
    expect(screen.getByText(/Searched 2 sources, found 3 passages/)).toBeTruthy();
    await userEvent.click(await screen.findByRole("button", { name: /Source 1: budget.pdf/ }));
    expect(props.onOpenCitation).toHaveBeenCalledWith(citation);
    expect(screen.getByText("[7]")).toBeTruthy(); // not a passage of this answer: plain text
  });

  it("makes a pill only of text: not in code, not in a link, and not from raw HTML a model wrote", async () => {
    const { container } = chat({
      state: {
        ...idle,
        messages: [
          ask("q"),
          answer({
            text: [
              "Real [1].",
              "",
              "`code [1]` and [a link [1]](https://example.com/x)",
              "",
              '<source-label n="1">fake</source-label>',
            ].join("\n"),
          }),
        ],
      },
    });
    await formatted(container);
    // one pill, for the one real label; the others are text
    expect(await screen.findAllByRole("button", { name: /Source 1/ })).toHaveLength(1);
    expect(container.querySelector("code")?.textContent).toBe("code [1]");
    expect(container.textContent).toContain("<source-label n=");
  });

  it("shows no passages count when none were found, and says one source in the singular", () => {
    chat({
      state: {
        ...idle,
        messages: [ask("q"), answer({ text: "No.", searched: { sources: 1, passages: 0 } })],
      },
    });
    expect(screen.getByText("Searched 1 source")).toBeTruthy();
  });
});

describe("the box", () => {
  it("sends on Enter, not while blocked, and says why", async () => {
    const onSend = vi.fn();
    const { rerender, props } = chat({ state: idle, onSend });
    await userEvent.type(screen.getByLabelText("Ask about your sources"), "Who is the CEO?{Enter}");
    expect(onSend).toHaveBeenCalledWith("Who is the CEO?");
    rerender(<NotebookChatNext {...props} scope="" blockedReason="Add a source first." />);
    await userEvent.type(screen.getByLabelText("Ask about your sources"), "x{Enter}");
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Add a source first.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Send" })).toHaveProperty("disabled", true);
  });

  it("shows the scope and the model chip in the box, and Stop while an answer arrives", async () => {
    const onStop = vi.fn();
    chat({
      state: {
        ...idle,
        phase: "answering",
        messages: [ask("q"), answer({ text: "Part", streaming: true })],
      },
      onStop,
      chip: <span>Llama 3</span>,
    });
    expect(screen.getByText("2 of 3 sources")).toBeTruthy();
    expect(screen.getByText("Llama 3")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Stop/ }));
    expect(onStop).toHaveBeenCalled();
    // no Copy or Save as note on an answer that is still arriving
    expect(screen.queryByRole("button", { name: "Copy reply" })).toBeNull();
  });

  it("puts a question from the guide in the box when its id changes", async () => {
    const { rerender, props } = chat({ state: idle, draftSeed: { text: "Summarise it", id: 1 } });
    await waitFor(() =>
      expect((screen.getByLabelText("Ask about your sources") as HTMLTextAreaElement).value).toBe(
        "Summarise it",
      ),
    );
    rerender(<NotebookChatNext {...props} draftSeed={{ text: "Who is the CEO?", id: 2 }} />);
    await waitFor(() =>
      expect((screen.getByLabelText("Ask about your sources") as HTMLTextAreaElement).value).toBe(
        "Who is the CEO?",
      ),
    );
  });

  it("lays out text written right to left right to left", () => {
    chat({ state: idle });
    expect(screen.getByLabelText("Ask about your sources").getAttribute("dir")).toBe("auto");
  });
});

describe("an empty notebook, a waiting answer and a failed one", () => {
  it("shows the guide and the hint, or the add-sources screen instead of them", () => {
    const { rerender, props } = chat({ state: idle, guide: <p>The guide</p> });
    expect(screen.getByText("The guide")).toBeTruthy();
    expect(screen.getByText(/Answers cite the passages they came from/)).toBeTruthy();
    rerender(
      <NotebookChatNext {...props} guide={undefined} empty={<p>Add your first source</p>} />,
    );
    expect(screen.getByText("Add your first source")).toBeTruthy();
    expect(screen.queryByText(/Answers cite the passages/)).toBeNull();
    expect(screen.getByLabelText("Ask about your sources")).toBeTruthy(); // the box stays
  });

  it("says the sources are being read until the first word arrives", () => {
    chat({
      state: {
        ...idle,
        phase: "searching",
        messages: [ask("q"), answer({ text: "", citations: [], streaming: true })],
      },
    });
    expect(screen.getByText("Reading your sources…")).toBeTruthy();
  });

  it("offers a retry for a retryable error and a way to the models for a missing one", async () => {
    const onRetry = vi.fn();
    const onNeedModel = vi.fn();
    const state = { ...idle, phase: "error" as const, messages: [ask("q")] };
    const { rerender, props } = chat({
      state: {
        ...state,
        error: { code: "language_failed", message: "It did not answer.", retryable: true },
      },
      onRetry,
      onNeedModel,
    });
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
    rerender(
      <NotebookChatNext
        {...props}
        state={{
          ...state,
          error: { code: "no_language_model", message: "None chosen.", retryable: false },
        }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Choose a model" }));
    expect(onNeedModel).toHaveBeenCalled();
  });

  it("tells a screen reader that an answer is coming and then says it once", async () => {
    const { rerender, props } = chat({
      state: {
        ...idle,
        phase: "answering",
        messages: [ask("q"), answer({ text: "Par", streaming: true })],
      },
    });
    expect(screen.getByText("The assistant is answering.")).toBeTruthy();
    rerender(
      <NotebookChatNext
        {...props}
        state={{
          ...idle,
          messages: [ask("q"), answer({ text: "Done here [1].", citations: [citation] })],
        }}
      />,
    );
    expect(await screen.findByText("Answer ready.")).toBeTruthy();
    expect(screen.getByRole("log").textContent).toBe("The assistant said: Done here [1].");
  });
});

describe("keeping an answer", () => {
  it("copies the reply, and keeps it as a note", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const onSaveNote = vi.fn();
    chat({ onSaveNote });
    await userEvent.click(screen.getByRole("button", { name: "Copy reply" }));
    expect(writeText).toHaveBeenCalledWith("It is $350,000 [1], plus tax [7].");
    await userEvent.click(screen.getByRole("button", { name: "Save as note" }));
    expect(onSaveNote).toHaveBeenCalledWith(expect.objectContaining({ id: "a" }));
  });

  it("has no edit, no answer again and no versions: a notebook conversation is a line, not a tree", () => {
    chat();
    expect(screen.queryByRole("button", { name: "Edit message" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Answer again" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Versions of this message" })).toBeNull();
  });
});

describe("a model's thinking", () => {
  it("shows Thinking collapsed, as plain text, for a model that returns it, and nothing for one that does not", async () => {
    const withThinking = chat({
      state: {
        ...idle,
        messages: [ask("q"), answer({ reasoning: "Let me check the <b>first</b> file." })],
      },
    });
    await formatted(withThinking.container);
    const details = withThinking.container.querySelector(
      "details[data-reasoning]",
    ) as HTMLDetailsElement;
    expect(details).not.toBeNull();
    expect(details.open).toBe(false);
    expect(details.textContent).toContain("Thinking");
    expect(details.querySelector("b")).toBeNull(); // the model's own text is never markup
    expect(details.textContent).toContain("<b>first</b>");
    withThinking.unmount();
    const without = chat();
    await formatted(without.container);
    expect(without.container.querySelector("details[data-reasoning]")).toBeNull();
  });

  it("says it is still thinking while the thinking arrives before any answer", () => {
    const { container } = chat({
      state: {
        ...idle,
        phase: "answering",
        messages: [
          ask("q"),
          answer({ text: "", citations: [], reasoning: "Hmm", streaming: true }),
        ],
      },
    });
    expect(container.querySelector("details[data-reasoning]")?.textContent).toContain("Thinking…");
  });
});

describe("what a model writes is never markup", () => {
  it("shows raw HTML as text, makes no picture from an address, and keeps links to http(s)", async () => {
    const { container } = chat({
      state: { ...idle, messages: [ask("q"), answer({ text: ADVERSARIAL, citations: [] })] },
    });
    await formatted(container);
    const shown = container.querySelector("[data-markdown]") as HTMLElement;
    for (const tag of ["script", "iframe", "img", "object", "embed", "style", "form"]) {
      expect(shown.querySelector(tag), `<${tag}> in the output`).toBeNull();
    }
    expect([...shown.querySelectorAll("a")].map((a) => a.getAttribute("href"))).toEqual([
      "https://example.com/page",
    ]);
  });
});

// ---- inside the workspace, with Labs on ---------------------------------------------------------------------------------

const ev = (event: string, data: Record<string, unknown> = {}, seq = 1): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq, ...data } }) as unknown as ParsedEvent;

const source = (id: string): NotebookSource => ({
  id,
  notebook_id: "n1",
  folder_id: null,
  title: `${id}.pdf`,
  kind: "file",
  status: "ready",
  error: null,
  mime: "application/pdf",
  suffix: ".pdf",
  size_bytes: 10,
  pages: 3,
  created_at: "2026-10-16T00:00:00Z",
  updated_at: "2026-10-16T00:00:00Z",
});

function workspace(events: ParsedEvent[]) {
  const api = {
    sources: vi.fn(async () => [{ ...source("s1"), title: "budget.pdf" }]),
    folders: vi.fn(async () => []),
    conversations: vi.fn(async () => []),
    outputs: vi.fn(async () => []),
    guide: vi.fn(async () => ({ guide: null, stale: false, ready: false })),
    addNote: vi.fn(async () => source("note")),
    conversation: vi.fn(async (): Promise<NotebookConversation> => {
      throw new Error("none");
    }),
    source: vi.fn(async () => ({
      ...source("s1"),
      content: "# Budget\n\nLine two.\n\nThe budget is $350,000.\n",
    })),
  } as unknown as NotebooksApi;
  const inputs: object[] = [];
  const runs = {
    startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
      inputs.push(input);
      for (const e of events) on(e);
    }),
    watchRun: vi.fn(async () => {}),
  };
  render(
    <NotebookWorkspace
      api={api}
      runs={runs}
      notebookId="n1"
      title="Launch plan"
      onTitle={vi.fn()}
      searchReady
      chatModelChosen
      ensureNotebook={async () => "n1"}
    />,
  );
  return { api, inputs };
}

describe("the notebook with the new chat switched on in Labs", () => {
  it("asks, shows the thinking and the search, makes a pill that opens the passage, and keeps a note", async () => {
    localStorage.setItem(CHAT_NEXT_KEY, "1");
    const { api, inputs } = workspace([
      ev("tool_call", { id: "c", name: "search_sources", arguments: { sources: 1 } }, 2),
      ev("tool_result", { id: "c", name: "search_sources", output: { hits: [{}] } }, 3),
      ev("reasoning", { node: "answer", text: "The budget is in the file." }, 4),
      ev("token", { text: "It is $350,000 [1]." }, 5),
      ev(
        "done",
        {
          outputs: {
            status: "done",
            reply: "It is $350,000 [1].",
            citations: [citation],
            conversation_id: "c1",
            title: "Budget",
          },
        },
        6,
      ),
    ]);
    const box = await screen.findByLabelText("Ask about your sources");
    await userEvent.type(box, "What is the budget?{Enter}");
    await waitFor(() => expect(inputs).toHaveLength(1));
    expect(inputs[0]).toMatchObject({ text: "What is the budget?", notebook_id: "n1" });
    expect(inputs[0]).not.toHaveProperty("document_ids");
    expect(await screen.findByText(/Searched 1 source, found 1 passages/)).toBeTruthy();
    expect(document.querySelector("details[data-reasoning]")?.textContent).toContain("Thinking");
    await userEvent.click(await screen.findByRole("button", { name: "Save as note" }));
    await waitFor(() => expect(api.addNote).toHaveBeenCalledTimes(1));
    const call = (api.addNote as unknown as ReturnType<typeof vi.fn>).mock.calls[0] ?? [];
    expect(call[2]).toBe("It is $350,000 [1].\n\nSources:\n[1] budget.pdf");
    await userEvent.click(await screen.findByRole("button", { name: /Source 1: budget.pdf/ }));
    await waitFor(() => expect(screen.getByLabelText("Back to sources")).toBeTruthy());
    expect(screen.getByText(/The budget is \$350,000\./)).toBeTruthy();
  });

  it("keeps the old chat while Labs is off", async () => {
    workspace([]);
    const box = await screen.findByLabelText("Ask about your sources");
    expect(box.tagName).toBe("TEXTAREA");
    // the old box is a plain textarea inside a form, not the library's composer
    expect(box.closest("form")).not.toBeNull();
    fireEvent.change(box, { target: { value: "x" } });
    expect(document.querySelector("[data-markdown]")).toBeNull();
  });
});
