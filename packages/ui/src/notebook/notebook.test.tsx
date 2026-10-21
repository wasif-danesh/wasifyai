// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  NotebookConversation,
  NotebookFolder,
  NotebookSource,
  NotebookSummary,
  NotebooksApi,
  OnEvent,
  ParsedEvent,
} from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { Markdown } from "../chat/markdown";
import { AddSources, fileProblem } from "./AddSources";
import { NotebookChat } from "./NotebookChat";
import { NotebookList } from "./NotebookList";
import { NotebookWorkspace } from "./NotebookWorkspace";
import { SetupCard } from "./SetupCard";
import { SourceViewer, splitAt } from "./SourceViewer";
import { SourcesPane } from "./SourcesPane";

const ev = (event: string, data: Record<string, unknown> = {}, seq = 1): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq, ...data } }) as unknown as ParsedEvent;

const source = (id: string, over: Partial<NotebookSource> = {}): NotebookSource => ({
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
  ...over,
});

const citation = {
  n: 1,
  chunk_id: 7,
  document_id: "s1",
  title: "budget.pdf",
  start_line: 3,
  end_line: 4,
  text: "The marketing budget is $350,000.",
};

describe("adding sources", () => {
  it("knows what the engine will not take before sending it", () => {
    expect(fileProblem({ name: "a.pdf", size: 10 })).toBeNull();
    expect(fileProblem({ name: "tool.exe", size: 10 })).toMatch(/cannot be added/);
    expect(fileProblem({ name: "big.pdf", size: 101 * 1024 * 1024 })).toMatch(/100 MB/);
    expect(fileProblem({ name: "empty.txt", size: 0 })).toMatch(/empty/);
  });

  it("hands over the files and the copied text, and says no to a bad file", async () => {
    const onFiles = vi.fn();
    const onNote = vi.fn();
    render(<AddSources onFiles={onFiles} onNote={onNote} />);
    const input = screen.getByLabelText("Choose files") as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "a.pdf"), new File(["x"], "bad.exe")] },
    });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles.mock.calls[0]?.[0]).toHaveLength(1);
    expect(screen.getByRole("alert").textContent).toMatch(/bad\.exe/);

    await userEvent.click(screen.getByRole("button", { name: /Copied text/ }));
    await userEvent.type(screen.getByLabelText("Text"), "Some words to remember");
    await userEvent.click(screen.getByRole("button", { name: "Add text" }));
    expect(onNote).toHaveBeenCalledWith("Pasted text", "Some words to remember");
    // websites are shown, and not yet
    expect(screen.getByRole("button", { name: /Websites/ })).toHaveProperty("disabled", true);
  });

  it("takes dropped files", () => {
    const onFiles = vi.fn();
    render(<AddSources onFiles={onFiles} onNote={vi.fn()} />);
    const zone = screen.getByRole("group", { name: "Drop files here" });
    fireEvent.drop(zone, { dataTransfer: { files: [new File(["x"], "notes.md")] } });
    expect(onFiles).toHaveBeenCalled();
  });
});

describe("the sources tree", () => {
  const folders: NotebookFolder[] = [
    { id: "f1", notebook_id: "n1", parent_id: null, name: "Reports" },
  ];
  function pane(over = {}) {
    const props = {
      sources: [source("s1", { folder_id: "f1" }), source("s2", { folder_id: "f1" }), source("s3")],
      folders,
      unticked: new Set<string>(),
      onUnticked: vi.fn(),
      onOpen: vi.fn(),
      onAdd: vi.fn(),
      onNewFolder: vi.fn(),
      onRename: vi.fn(),
      onRemove: vi.fn(),
      onRetry: vi.fn(),
      onCancel: vi.fn(),
      onMove: vi.fn(),
      onRenameFolder: vi.fn(),
      onRemoveFolder: vi.fn(),
      ...over,
    };
    render(<SourcesPane {...props} />);
    return props;
  }

  it("ticks a folder as a whole and a source on its own", async () => {
    const p = pane();
    await userEvent.click(screen.getByLabelText("Use everything in Reports"));
    const first = p.onUnticked.mock.calls[0]?.[0] as Set<string>;
    expect([...first].sort()).toEqual(["s1", "s2"]);
    await userEvent.click(screen.getByLabelText("Use s3.pdf"));
    const second = p.onUnticked.mock.calls[1]?.[0] as Set<string>;
    expect([...second]).toEqual(["s3"]);
  });

  it("renames and removes in boxes of the page, never with window.confirm or window.prompt", async () => {
    // the app window has neither: they answer "no" at once
    vi.stubGlobal("confirm", () => {
      throw new Error("window.confirm is not available in the app window");
    });
    vi.stubGlobal("prompt", () => {
      throw new Error("window.prompt is not available in the app window");
    });
    const p = pane();
    await userEvent.click(screen.getByLabelText("Rename s3.pdf"));
    const field = screen.getByLabelText("Name");
    expect(field).toHaveProperty("value", "s3.pdf");
    await userEvent.clear(field);
    await userEvent.type(field, "budget.pdf{Enter}");
    expect(p.onRename).toHaveBeenCalledWith(expect.objectContaining({ id: "s3" }), "budget.pdf");

    await userEvent.click(screen.getByLabelText("Remove s3.pdf"));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(p.onRemove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByLabelText("Remove s3.pdf"));
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(p.onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: "s3" }));

    await userEvent.click(screen.getByLabelText("Remove folder Reports"));
    expect(screen.getByText(/and the 2 sources in it/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(p.onRemoveFolder).toHaveBeenCalledWith(expect.objectContaining({ id: "f1" }));
    await userEvent.click(screen.getByLabelText("Rename Reports"));
    await userEvent.type(screen.getByLabelText("Name"), "Reports 2025{Enter}"); // the name starts selected
    expect(p.onRenameFolder).toHaveBeenCalledWith(
      expect.objectContaining({ id: "f1" }),
      "Reports 2025",
    );
    vi.unstubAllGlobals();
  });

  it("shows a half-ticked folder as mixed", () => {
    pane({ unticked: new Set(["s1"]) });
    const box = screen.getByLabelText("Use everything in Reports") as HTMLInputElement;
    expect(box.indeterminate).toBe(true);
  });

  it("opens a folder, and offers to read a failed source again with its reason", async () => {
    const p = pane({
      sources: [
        source("s1", { folder_id: "f1" }),
        source("s9", { status: "failed", error: "No text could be read from this file." }),
      ],
    });
    expect(screen.queryByText("s1.pdf")).toBeNull(); // the folder is closed
    await userEvent.click(screen.getByRole("button", { name: /^Reports/ }));
    expect(screen.getByText("s1.pdf")).toBeTruthy();
    expect(screen.getByText("No text could be read from this file.")).toBeTruthy();
    await userEvent.click(screen.getByLabelText("Read s9.pdf again"));
    expect(p.onRetry).toHaveBeenCalled();
  });

  it("shows reading and being waited for", () => {
    pane({
      sources: [source("a", { status: "processing" }), source("b", { status: "pending" })],
    });
    expect(screen.getByText("Reading…")).toBeTruthy();
    expect(screen.getByText("Waiting")).toBeTruthy();
  });

  it("says what is empty", () => {
    pane({ sources: [], folders: [] });
    expect(screen.getByText(/Saved sources appear here/)).toBeTruthy();
  });
});

describe("answers with citations", () => {
  it("renders a label as a button that opens its passage, and leaves unknown ones as text", async () => {
    const onOpen = vi.fn();
    render(
      <NotebookChat
        state={{
          conversationId: "c1",
          title: "",
          phase: "idle",
          error: null,
          runId: null,
          lastSeq: 0,
          messages: [
            { id: "u", role: "user", text: "What is the budget?", citations: [] },
            {
              id: "a",
              role: "assistant",
              text: "It is $350,000 [1], plus tax [7].",
              citations: [citation],
              searched: { sources: 2, passages: 3 },
            },
          ],
        }}
        onSend={vi.fn()}
        onStop={vi.fn()}
        onRetry={vi.fn()}
        onOpenCitation={onOpen}
        scope="2 sources"
      />,
    );
    expect(await screen.findByText(/Searched 2 sources, found 3 passages/)).toBeTruthy();
    await userEvent.click(await screen.findByRole("button", { name: /Source 1: budget.pdf/ }));
    expect(onOpen).toHaveBeenCalledWith(citation);
    expect(screen.getByText("[7]")).toBeTruthy(); // not a passage of this answer: plain text
  });

  it("sends on Enter, not while blocked, and says why", async () => {
    const onSend = vi.fn();
    const state = {
      conversationId: null,
      title: "",
      phase: "idle" as const,
      error: null,
      runId: null,
      lastSeq: 0,
      messages: [],
    };
    const { rerender } = render(
      <NotebookChat
        state={state}
        onSend={onSend}
        onStop={vi.fn()}
        onRetry={vi.fn()}
        onOpenCitation={vi.fn()}
        scope="3 sources"
      />,
    );
    const box = screen.getByLabelText("Ask about your sources");
    await userEvent.type(box, "Who is the CEO?{Enter}");
    expect(onSend).toHaveBeenCalledWith("Who is the CEO?");
    rerender(
      <NotebookChat
        state={state}
        onSend={onSend}
        onStop={vi.fn()}
        onRetry={vi.fn()}
        onOpenCitation={vi.fn()}
        scope=""
        blockedReason="Add a source first."
      />,
    );
    await userEvent.type(screen.getByLabelText("Ask about your sources"), "x{Enter}");
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("Add a source first.").length).toBeGreaterThan(0); // chat and Studio
    expect(screen.getByRole("button", { name: "Send" })).toHaveProperty("disabled", true);
  });

  it("offers a retry for a retryable error and a way to the models for a missing one", async () => {
    const retry = vi.fn();
    const need = vi.fn();
    const base = {
      conversationId: null,
      title: "",
      phase: "error" as const,
      runId: null,
      lastSeq: 0,
      messages: [{ id: "u", role: "user" as const, text: "q", citations: [] }],
    };
    const { rerender } = render(
      <NotebookChat
        state={{
          ...base,
          error: { code: "language_failed", message: "It did not answer.", retryable: true },
        }}
        onSend={vi.fn()}
        onStop={vi.fn()}
        onRetry={retry}
        onOpenCitation={vi.fn()}
        scope=""
        onNeedModel={need}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
    rerender(
      <NotebookChat
        state={{
          ...base,
          error: { code: "no_language_model", message: "None chosen.", retryable: false },
        }}
        onSend={vi.fn()}
        onStop={vi.fn()}
        onRetry={retry}
        onOpenCitation={vi.fn()}
        scope=""
        onNeedModel={need}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Choose a model" }));
    expect(need).toHaveBeenCalled();
  });
});

describe("markdown with labels and tables", () => {
  it("renders a table and a label callback", () => {
    render(
      <Markdown
        text={"| Region | Revenue |\n|---|---|\n| APAC | 1.7 [2] |\n"}
        renderLabel={(n) => <b data-testid="label">{`#${n}`}</b>}
      />,
    );
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.getByText("APAC")).toBeTruthy();
    expect(screen.getByTestId("label").textContent).toBe("#2");
  });

  it("leaves a link that looks like a label alone", () => {
    render(<Markdown text="[1](https://example.com) and [2]" renderLabel={(n) => <i>{n}</i>} />);
    expect(screen.getByRole("link").textContent).toBe("1");
  });
});

describe("a source opened from a citation", () => {
  it("cuts the text at the cited lines", () => {
    const parts = splitAt("a\nb\nc\nd\ne", 2, 3);
    expect(parts).toEqual({ before: "a", mark: "b\nc", after: "d\ne" });
    expect(splitAt("a", null, null)).toBeNull();
    expect(splitAt("a\nb", 5, 6)).toBeNull();
  });

  it("shows the source with the passage marked, and the passage alone when it is gone", async () => {
    const api = {
      source: vi.fn(async (_n: string, id: string) => {
        if (id === "gone") throw Object.assign(new Error("not found"), { status: 404 });
        return source("s1", {
          content: "# Budget\n\nOpening line.\n\nThe budget is $350,000.\n\nClosing.",
        });
      }),
    } as unknown as NotebooksApi;
    const { rerender } = render(
      <SourceViewer
        api={api}
        notebookId="n1"
        sourceId="s1"
        onBack={vi.fn()}
        highlight={{ start: 5, end: 5 }}
      />,
    );
    await waitFor(() => expect(screen.getByText(/The budget is \$350,000\./)).toBeTruthy());
    expect(screen.getByText("Opening line.")).toBeTruthy();
    rerender(
      <SourceViewer
        api={api}
        notebookId="n1"
        sourceId="gone"
        onBack={vi.fn()}
        highlight={{ start: 1, end: 2, snapshot: "The marketing budget is $350,000." }}
      />,
    );
    await waitFor(() => expect(screen.getByText(/was removed from the notebook/)).toBeTruthy());
    expect(screen.getByText("The marketing budget is $350,000.")).toBeTruthy();
  });
});

describe("the setup card", () => {
  it("asks with the size before fetching, and shows progress", async () => {
    const onStart = vi.fn();
    const { rerender } = render(
      <SetupCard
        onStart={onStart}
        items={[
          {
            id: "search",
            title: "Search model",
            why: "Finds passages.",
            bytes: 67_176_520,
            state: "missing",
            required: true,
          },
          {
            id: "reader",
            title: "Document reader",
            why: "Reads PDFs.",
            bytes: 1_466_177_706,
            state: "ready",
            required: false,
          },
        ]}
      />,
    );
    expect(screen.queryByText("Document reader")).toBeNull(); // ready: not shown
    await userEvent.click(screen.getByRole("button", { name: "Set up" }));
    expect(screen.getByText(/Download 67 MB now\?/)).toBeTruthy();
    expect(onStart).not.toHaveBeenCalled();
    await userEvent.click(
      within(screen.getByLabelText("Set up notebooks")).getAllByRole("button", {
        name: "Set up",
      })[0] as HTMLElement,
    );
    expect(onStart).toHaveBeenCalledWith("search");
    rerender(
      <SetupCard
        onStart={onStart}
        items={[
          {
            id: "search",
            title: "Search model",
            why: "x",
            bytes: 1,
            state: "working",
            fraction: 0.5,
            message: "Downloading",
            required: true,
          },
        ]}
      />,
    );
    expect(screen.getByText("Downloading")).toBeTruthy();
  });
});

describe("the notebooks list", () => {
  const nb = (id: string, title: string, over: Partial<NotebookSummary> = {}): NotebookSummary => ({
    id,
    title,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    opened_at: null,
    sources: 2,
    ready: 2,
    reading: 0,
    failed: 0,
    ...over,
  });

  it("offers the first notebook when there are none", async () => {
    const onCreate = vi.fn();
    render(
      <NotebookList
        notebooks={[]}
        onOpen={vi.fn()}
        onCreate={onCreate}
        onRename={vi.fn()}
        onRemove={vi.fn()}
      />,
    );
    expect(screen.getByText("Start your first notebook")).toBeTruthy();
    await userEvent.click(
      screen.getAllByRole("button", { name: /New notebook/ })[0] as HTMLElement,
    );
    expect(onCreate).toHaveBeenCalled();
  });

  it("lists cards with counts and finds by what is inside", async () => {
    const find = vi.fn(async () => ["n3"]);
    const onOpen = vi.fn();
    render(
      <NotebookList
        notebooks={[
          nb("n1", "Q3 planning", { reading: 1 }),
          nb("n2", "Thesis"),
          nb("n3", "Misc"),
          nb("n4", "More"),
        ]}
        onOpen={onOpen}
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onRemove={vi.fn()}
        onFind={find}
      />,
    );
    expect(screen.getByText("2 sources, 1 being read")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("Find a notebook"), "warranty");
    await waitFor(() => expect(find).toHaveBeenCalledWith("warranty"));
    await waitFor(() => expect(screen.queryByText("Q3 planning")).toBeNull());
    await userEvent.click(screen.getByText("Misc"));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "n3" }));
  });
});

describe("a notebook", () => {
  function fakeApi() {
    const sources: NotebookSource[] = [];
    const api = {
      sources: vi.fn(async () => [...sources]),
      folders: vi.fn(async () => []),
      conversations: vi.fn(async () => []),
      outputs: vi.fn(async () => []),
      guide: vi.fn(async () => ({ guide: null, stale: false, ready: false })),
      addNote: vi.fn(async (_n: string, title: string) =>
        source(`n${title.length}`, { title, kind: "note" }),
      ),
      conversation: vi.fn(async (): Promise<NotebookConversation> => {
        throw new Error("none");
      }),
      upload: vi.fn(async (_n: string, files: File[]) => {
        for (const f of files) sources.push(source(`s${sources.length + 1}`, { title: f.name }));
        return { created: [], duplicates: [], rejected: [] };
      }),
      source: vi.fn(async (_n: string, id: string) => ({
        ...(sources.find((s) => s.id === id) as NotebookSource),
        content: "# Budget\n\nLine two.\n\nThe budget is $350,000.\n",
      })),
    } as unknown as NotebooksApi;
    return { api, sources };
  }

  it("opens a new notebook on the add-sources screen, saves it with the first file, then answers", async () => {
    const { api } = fakeApi();
    const inputs: object[] = [];
    const runs = {
      startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
        inputs.push(input);
        on(ev("tool_call", { id: "c", name: "search_sources", arguments: { sources: 1 } }, 2));
        on(ev("tool_result", { id: "c", name: "search_sources", output: { hits: [{}] } }, 3));
        on(ev("token", { text: "It is $350,000 [1]." }, 4));
        on(
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
            5,
          ),
        );
      }),
      watchRun: vi.fn(async () => {}),
    };
    const ensure = vi.fn(async () => "n1");

    function Harness() {
      const [id, setId] = (require("react") as typeof import("react")).useState<string | null>(
        null,
      );
      return (
        <NotebookWorkspace
          api={api}
          runs={runs}
          notebookId={id}
          title="Untitled notebook"
          onTitle={vi.fn()}
          searchReady
          chatModelChosen
          ensureNotebook={async () => {
            const made = await ensure();
            setId(made);
            return made;
          }}
        />
      );
    }
    render(<Harness />);
    // a draft: the add-sources screen, and nothing to ask yet (the chat is a separate chunk, so wait for it)
    expect(await screen.findByText("Let’s start your notebook")).toBeTruthy();
    expect(screen.getAllByText("Add a source first.").length).toBeGreaterThan(0); // chat and Studio
    fireEvent.change(screen.getByLabelText("Choose files"), {
      target: { files: [new File(["x"], "budget.pdf")] },
    });
    await waitFor(() => expect(ensure).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText("budget.pdf")).toBeTruthy());
    // Studio is there and not yet available
    expect(screen.getByRole("button", { name: "Report" })).toBeTruthy();

    await userEvent.type(
      screen.getByLabelText("Ask about your sources"),
      "What is the budget?{Enter}",
    );
    await waitFor(() => expect(inputs).toHaveLength(1));
    expect(inputs[0]).toMatchObject({ text: "What is the budget?", notebook_id: "n1" });
    expect(inputs[0]).not.toHaveProperty("document_ids"); // nothing unticked: every source
    // an answer can be kept as a note: a source like the others, with the sources it cited
    await userEvent.click(await screen.findByRole("button", { name: "Save as note" }));
    const addNote = api.addNote as unknown as ReturnType<typeof vi.fn>;
    await waitFor(() => expect(addNote).toHaveBeenCalledTimes(1));
    const call = addNote.mock.calls[0] ?? [];
    expect(call[1]).toBe("What is the budget?");
    expect(call[2]).toBe("It is $350,000 [1].\n\nSources:\n[1] budget.pdf");
    expect(await screen.findByText("Saved as a note in your sources.")).toBeTruthy();
    const pill = await screen.findByRole("button", { name: /Source 1: budget.pdf/ });
    await userEvent.click(pill);
    await waitFor(() => expect(screen.getByLabelText("Back to sources")).toBeTruthy());
    expect(screen.getByText(/The budget is \$350,000\./)).toBeTruthy();
  });
});
