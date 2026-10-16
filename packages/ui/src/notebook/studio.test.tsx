// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  FlashcardsData,
  NotebookOutput,
  NotebooksApi,
  OnEvent,
  ParsedEvent,
  QuizData,
} from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import {
  AudioScriptViewer,
  FlashcardsViewer,
  InfographicViewer,
  MindMapViewer,
  OutputViewer,
  QuizViewer,
  SlidesViewer,
  TableViewer,
} from "./OutputViewers";
import { SourceGuide } from "./SourceGuide";
import { StudioPane } from "./StudioPane";
import { parseOutline } from "./outputs";

const ev = (event: string, data: Record<string, unknown> = {}, seq = 1): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq, ...data } }) as unknown as ParsedEvent;

const output = (over: Partial<NotebookOutput> = {}): NotebookOutput => ({
  id: "o1",
  notebook_id: "n1",
  format: "report",
  title: "Launch plan",
  status: "ready",
  error: null,
  prompt: "",
  source_ids: [],
  has_file: true,
  file_name: "launch-plan.md",
  file_mime: "text/markdown",
  created_at: "2026-10-16T00:00:00Z",
  updated_at: "2026-10-16T00:00:00Z",
  ...over,
});

const deck: FlashcardsData = {
  title: "Facts",
  cards: [
    { front: "What is the budget?", back: "$350,000." },
    { front: "How many people?", back: "48." },
  ],
};
const quiz: QuizData = {
  title: "Quiz",
  questions: [
    {
      question: "Budget?",
      options: ["$1", "$350,000", "$3", "$4"],
      answer_index: 1,
      explanation: "It is $350,000.",
    },
    { question: "People?", options: ["10", "20", "48", "50"], answer_index: 2, explanation: "" },
  ],
};

describe("viewers", () => {
  it("turns flashcards over and moves between them", async () => {
    render(<FlashcardsViewer deck={deck} />);
    expect(screen.getByText("Card 1 of 2")).toBeTruthy();
    expect(screen.getByText("What is the budget?")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Show the answer" }));
    expect(screen.getByText("$350,000.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(screen.getByText("Card 2 of 2")).toBeTruthy();
    expect(screen.getByText("How many people?")).toBeTruthy(); // a new card shows its question
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByText("Card 1 of 2")).toBeTruthy();
    await userEvent.keyboard(" ");
    expect(screen.getByText("$350,000.")).toBeTruthy();
  });

  it("scores a quiz, shows the reason, and can be tried again", async () => {
    render(<QuizViewer quiz={quiz} />);
    await userEvent.click(screen.getByRole("button", { name: "$1" })); // wrong
    expect(screen.getByLabelText("Wrong")).toBeTruthy();
    expect(screen.getByLabelText("Correct")).toBeTruthy();
    expect(screen.getByText("It is $350,000.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Next question/ }));
    await userEvent.click(screen.getByRole("button", { name: "48" })); // right
    await userEvent.click(screen.getByRole("button", { name: /See the score/ }));
    expect(screen.getByText("You got 1 of 2")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(screen.getByText("Question 1 of 2")).toBeTruthy();
  });

  it("reads an outline as a tree and opens it branch by branch", async () => {
    const md =
      "# Launch\n- Budget\n  - $350,000\n  - Marketing\n- People\n  - Engineering\n    - 48 people\n";
    const tree = parseOutline(md);
    expect(tree.title).toBe("Launch");
    expect(tree.roots.map((r) => r.label)).toEqual(["Budget", "People"]);
    expect(tree.roots[1]?.children[0]?.children[0]?.label).toBe("48 people");
    render(<MindMapViewer markdown={md} />);
    expect(screen.getByText("$350,000")).toBeTruthy(); // the first branch is open
    expect(screen.queryByText("48 people")).toBeNull(); // a deeper branch starts closed
    await userEvent.click(screen.getByRole("button", { name: "Engineering" }));
    expect(screen.getByText("48 people")).toBeTruthy();
  });

  it("shows the right viewer for a format, a failure's reason, and the file to save", async () => {
    const save = vi.fn();
    const { rerender } = render(
      <OutputViewer
        output={output({ format: "flashcards", data: deck })}
        onBack={vi.fn()}
        onDownload={save}
      />,
    );
    expect(screen.getByText("Card 1 of 2")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Save launch-plan.md/ }));
    expect(save).toHaveBeenCalled();
    rerender(
      <OutputViewer
        output={output({ body: "# Launch plan\n\n## Budget\n\nIt is **$350,000**." })}
        onBack={vi.fn()}
      />,
    );
    expect(screen.getByText("$350,000")).toBeTruthy();
    rerender(
      <OutputViewer
        output={output({ status: "failed", error: "The reply could not be used." })}
        onBack={vi.fn()}
      />,
    );
    expect(screen.getByText("The reply could not be used.")).toBeTruthy();
  });
});

describe("the Studio pane", () => {
  function setup(
    opts: { outputs?: NotebookOutput[]; blocked?: string | null; ids?: string[] } = {},
  ) {
    const list = opts.outputs ?? [];
    const api = {
      outputs: vi.fn(async () => [...list]),
      output: vi.fn(async (_n: string, id: string) => ({
        ...(list.find((o) => o.id === id) as NotebookOutput),
        body: "# Launch plan\n\nBody.",
      })),
      renameOutput: vi.fn(async () => {}),
      removeOutput: vi.fn(async () => {}),
      cancelOutput: vi.fn(async () => {}),
      outputFile: vi.fn(async () => new Blob(["x"])),
    } as unknown as NotebooksApi;
    const inputs: object[] = [];
    const runs = {
      startRun: vi.fn(async (_p: string, input: object, _s: AbortSignal, on: OnEvent) => {
        inputs.push(input);
        on(ev("node", { node: "write", status: "started", label: "Writing the report" }, 1));
        list.unshift(output({ id: "o2", title: "New report" }));
        on(ev("done", { outputs: { status: "done", artifact_id: "o2", title: "New report" } }, 2));
      }),
    };
    render(
      <StudioPane
        api={api}
        runs={runs}
        notebookId="n1"
        documentIds={opts.ids}
        scopeLabel="3 sources"
        blockedReason={opts.blocked ?? null}
      />,
    );
    return { api, runs, inputs, list };
  }

  it("explains why nothing can be made, and keeps the tiles still", () => {
    setup({ blocked: "Choose a chat model to make things from your sources." });
    expect(screen.getByText("Choose a chat model to make things from your sources.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Report" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Slide deck" })).toHaveProperty("disabled", true);
    expect(screen.queryByText("Soon")).toBeNull(); // every tile is built now
  });

  it("opens a brief, makes the output from the ticked sources, and lists it", async () => {
    const { inputs } = setup({ ids: ["d1", "d2"] });
    await userEvent.click(screen.getByRole("button", { name: "Quiz" }));
    expect(screen.getByText(/Made from 3 sources/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText(/Focus/), "the launch");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(inputs).toHaveLength(1));
    expect(inputs[0]).toEqual({
      notebook_id: "n1",
      studio: { format: "quiz", prompt: "the launch" },
      document_ids: ["d1", "d2"],
    });
    await waitFor(() => expect(screen.getByText("New report")).toBeTruthy());
  });

  it("opens an output in place and goes back", async () => {
    setup({ outputs: [output({ id: "o1", title: "Launch plan" })] });
    await userEvent.click(await screen.findByRole("button", { name: "Launch plan" }));
    await waitFor(() => expect(screen.getByLabelText("Back to Studio")).toBeTruthy());
    expect(screen.getByText("Body.")).toBeTruthy();
    await userEvent.click(screen.getByLabelText("Back to Studio"));
    expect(screen.getByRole("button", { name: "Report" })).toBeTruthy();
  });

  it("shows a failure with its reason, and an output being made with a stop", async () => {
    setup({
      outputs: [
        output({
          id: "f",
          title: "Quiz",
          format: "quiz",
          status: "failed",
          error: "The reply could not be used (no questions).",
        }),
        output({ id: "p", title: "", status: "processing" }),
      ],
    });
    expect(await screen.findByText("The reply could not be used (no questions).")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Stop/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Make it again" })).toBeTruthy();
  });
});

describe("more viewers", () => {
  it("steps through slides and shows their notes", async () => {
    render(
      <SlidesViewer
        deck={{
          title: "Launch",
          slides: [
            { title: "Budget", bullets: ["$350,000 for marketing"], notes: "Board approved." },
            { title: "People", bullets: ["48 in engineering"], notes: "" },
          ],
        }}
      />,
    );
    expect(screen.getByText("Slide 1 of 2")).toBeTruthy();
    expect(screen.getByText("$350,000 for marketing")).toBeTruthy();
    expect(screen.getByText("Board approved.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(screen.getByText("48 in engineering")).toBeTruthy();
  });

  it("shows a table, and an audio script", () => {
    render(
      <TableViewer
        table={{ title: "T", columns: ["Team", "People"], rows: [["Engineering", "48"]] }}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Team" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "48" })).toBeTruthy();
    render(
      <AudioScriptViewer
        script={{
          title: "Overview",
          hosts: ["Alex", "Sam"],
          audio: false,
          turns: [
            { speaker: 1, host: "Alex", text: "What is in the plan?" },
            { speaker: 2, host: "Sam", text: "A March launch." },
          ],
        }}
      />,
    );
    expect(screen.getByText("This is the script of the conversation.")).toBeTruthy();
    expect(screen.getByText("A March launch.")).toBeTruthy();
  });

  it("shows the picture of an infographic and says the facts under it are the exact ones", async () => {
    const imageUrl = vi.fn(async () => "http://127.0.0.1:1/files/img.png");
    render(
      <InfographicViewer
        imageUrl={imageUrl}
        info={{
          title: "Launch",
          summary: "A March launch.",
          image_id: "img-1",
          sections: [{ label: "Budget", value: "$350,000", detail: "Marketing" }],
        }}
      />,
    );
    const img = await screen.findByRole("img", { name: "Launch" });
    expect(img.getAttribute("src")).toBe("http://127.0.0.1:1/files/img.png");
    expect(imageUrl).toHaveBeenCalledWith("img-1");
    expect(screen.getByText(/can misspell words and misdraw numbers/)).toBeTruthy();
    expect(screen.getByText("$350,000")).toBeTruthy();
  });
});

describe("the source guide", () => {
  const guide = {
    summary: "These sources describe a launch.",
    topics: ["Budget", "Team"],
    questions: ["When is the launch?", "What is the budget?"],
  };

  it("shows the summary, the topics and questions that fill the box", async () => {
    const onAsk = vi.fn();
    render(
      <SourceGuide
        state={{ guide, stale: false, ready: true }}
        making={false}
        problem={null}
        onMake={vi.fn()}
        onAsk={onAsk}
      />,
    );
    expect(screen.getByText("These sources describe a launch.")).toBeTruthy();
    expect(screen.getByText("Budget")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "What is the budget?" }));
    expect(onAsk).toHaveBeenCalledWith("What is the budget?");
    expect(screen.queryByRole("button", { name: /update/ })).toBeNull();
  });

  it("says when it is being written, offers to update a stale one, and retries a failure", async () => {
    const onMake = vi.fn();
    const { rerender } = render(
      <SourceGuide
        state={{ guide: null, stale: false, ready: true }}
        making
        problem={null}
        onMake={onMake}
        onAsk={vi.fn()}
      />,
    );
    expect(screen.getByText(/Reading your sources to write a summary/)).toBeTruthy();
    rerender(
      <SourceGuide
        state={{ guide, stale: true, ready: true }}
        making={false}
        problem={null}
        onMake={onMake}
        onAsk={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Sources changed, update/ }));
    expect(onMake).toHaveBeenCalledTimes(1);
    rerender(
      <SourceGuide
        state={{ guide: null, stale: false, ready: true }}
        making={false}
        problem="The model did not answer."
        onMake={onMake}
        onAsk={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert").textContent).toBe("The model did not answer.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onMake).toHaveBeenCalledTimes(2);
  });

  it("shows nothing when there is no guide and nothing is happening", () => {
    const { container } = render(
      <SourceGuide
        state={{ guide: null, stale: false, ready: false }}
        making={false}
        problem={null}
        onMake={vi.fn()}
        onAsk={vi.fn()}
      />,
    );
    expect(container.textContent).toBe("");
  });
});

describe("the audio overview's voices", () => {
  const script = (audio = false) => ({
    title: "Overview",
    hosts: ["Alex", "Sam"],
    audio,
    turns: [
      { speaker: 1 as const, host: "Alex", text: "What is in the plan?" },
      { speaker: 2 as const, host: "Sam", text: "A March launch." },
    ],
  });
  const idle = { state: "idle" as const, done: 0, total: 0, message: "" };

  it("speaks the script on a click, follows it, and tells the screen when it is done", async () => {
    const changed = vi.fn();
    const control = {
      state: vi
        .fn()
        .mockResolvedValueOnce(idle)
        .mockResolvedValue({ state: "ready", done: 4, total: 4, message: "" }),
      start: vi.fn(async () => ({ state: "working" as const, done: 1, total: 4, message: "" })),
      audio: vi.fn(),
      changed,
    };
    const user = userEvent.setup();
    render(<AudioScriptViewer script={script()} control={control} />);
    await user.click(await screen.findByRole("button", { name: "Speak it" }));
    expect(control.start).toHaveBeenCalled();
    await waitFor(() => expect(changed).toHaveBeenCalled());
  });

  it("plays the finished overview and offers to make it again", async () => {
    URL.createObjectURL = vi.fn(() => "blob:overview");
    URL.revokeObjectURL = vi.fn();
    const control = {
      state: vi.fn(async () => ({ state: "ready" as const, done: 2, total: 2, message: "" })),
      start: vi.fn(),
      audio: vi.fn(async () => new Blob(["RIFF"])),
      changed: vi.fn(),
    };
    render(<AudioScriptViewer script={script(true)} control={control} />);
    const player = await screen.findByLabelText("The audio overview");
    expect(player).toHaveAttribute("src", "blob:overview");
    expect(screen.getByRole("button", { name: "Make it again" })).toBeTruthy();
  });

  it("says why the voices could not be made", async () => {
    const control = {
      state: vi.fn(async () => idle),
      start: vi.fn(async () => {
        throw new Error("Kokoro 82M is not on this computer yet. Get it in Models.");
      }),
      audio: vi.fn(),
      changed: vi.fn(),
    };
    const user = userEvent.setup();
    render(<AudioScriptViewer script={script()} control={control} />);
    await user.click(await screen.findByRole("button", { name: "Speak it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Get it in Models");
  });
});
