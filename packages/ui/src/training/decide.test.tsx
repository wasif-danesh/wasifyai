import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
// @vitest-environment jsdom
import type {
  DecisionExample,
  DecisionPlan,
  DecisionSet,
  DecisionStatus,
  Said,
  TrainRun,
  TrainedModel,
  TrainingApi,
  TrainingSetupState,
} from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Decide, DecideResult, parseCells, parseTable } from "./Decide";

afterEach(cleanup);

const STATUS: DecisionStatus = {
  ready: true,
  problem: null,
  engine: {},
  fit: { verdict: "fits", reason: "" },
  busy: false,
  active_run: null,
  place: "device",
  min_examples: 20,
  good_examples: 60,
  min_per_answer: 5,
  max_options: 12,
  levels: [3, 10, 5],
  kinds: ["yes_no", "category", "score"],
  rights: ["mine", "permission"],
  qualities: ["quick", "better"],
  choices: {
    family: "decision",
    default_base: "laya-english",
    default_method: "full",
    bases: [],
  },
  bases: [],
};

const said = (answer: string, confidence: number): Said => ({
  answer,
  confidence,
  shares: { [answer]: confidence, other: 1 - confidence },
});

function planFor(
  rows: DecisionExample[],
  rights: string,
  answers: string[],
  problem: string | null,
): DecisionPlan {
  const n = rows.length;
  const missing = problem
    ? problem
    : n < 20
      ? `Add at least 20 examples. You have ${n}. 60 or more is better.`
      : rights === ""
        ? "Say whose these texts are first."
        : null;
  return {
    examples: n,
    dropped: [],
    checks:
      n < 20
        ? [{ level: "error", code: "too_few", message: missing as string }]
        : [{ level: "warn", code: "few", message: `Only ${n} examples: it will be less sure.` }],
    counts: Object.fromEntries(answers.map((a) => [a, rows.filter((r) => r.answer === a).length])),
    steps: 20,
    passes: 4,
    estimate: "Under a minute",
    base: "laya-english",
    base_title: "Laya",
    base_note: "Reads English texts and answers with how sure it is.",
    held_back: 4,
    missing,
  };
}

const MODEL: TrainedModel = {
  id: "m".repeat(32),
  run_id: "r".repeat(32),
  dataset_id: "s".repeat(32),
  name: "Support messages",
  trigger_word: "",
  kind: "decision",
  base: "laya-english",
  preview: false,
  adapter_bytes: 846_000_000,
  created_at: "",
  card: {
    base_title: "Laya",
    licence: "Apache-2.0",
    engine: "laya",
    preview: false,
    note: "",
    dataset: { name: "Support messages", kind: "decision", examples: 60, hash: "h" },
    steps: 20,
    seconds: 40,
    trigger_word: "",
    statement: "",
    evaluation: {
      passed: true,
      note: "On 12 texts it had not seen, it was right 11 times (92 percent). Counting words alone was right 9 times (75 percent).",
      at: "",
    },
    trained_at: "",
    question: {
      kind: "category",
      text: "Which team should handle this message?",
      levels: 5,
      low: "",
      high: "",
      options: [
        { label: "billing", about: "money" },
        { label: "bug", about: "broken" },
        { label: "other", about: "" },
      ],
    },
    report: {
      texts: 12,
      right: { before: 5, after: 11, word_counter: 9, exactly: 11 },
      percent: { before: 42, after: 92, word_counter: 75 },
      per_answer: [
        { answer: "billing", of: 4, right: 4 },
        { answer: "bug", of: 4, right: 3 },
        { answer: "other", of: 4, right: 4 },
      ],
      mix_ups: [{ right: "bug", said: "other", times: 1 }],
      confidence: {
        note: "When it said it was at least 80 percent sure, it was right 10 of 10 times.",
        sure: 10,
        sure_right: 10,
      },
      wrong: [{ text: "It froze when I paid", right: "bug", said: "other", confidence: 0.55 }],
      passed: true,
      note: "On 12 texts it had not seen, it was right 11 times (92 percent).",
    },
    peek: [
      { text: "My invoice is wrong", before: said("other", 0.4), after: said("billing", 0.97) },
    ],
  },
};

const OFFER: TrainingSetupState = {
  installed: false,
  tool: null,
  base: null,
  problem: null,
  plan: {
    supported: true,
    bytes: 1_013_795_574,
    needs_free_bytes: 4_200_000_000,
    parts: [
      {
        name: "Trainer (Laya and PyTorch)",
        version: "0.4.15",
        bytes: 167_600_000,
        have: false,
        licence: "Apache-2.0",
        source: "pypi.org",
      },
      {
        name: "Laya",
        version: "the model it learns on",
        bytes: 846_195_574,
        have: false,
        licence: "Apache-2.0",
        source: "huggingface.co",
      },
    ],
  },
  progress: { state: "idle", step: null, steps: [], message: "", done_bytes: 0, total_bytes: 0 },
};

function fake(
  opts: { status?: Partial<DecisionStatus>; sets?: DecisionSet[]; setup?: TrainingSetupState } = {},
) {
  let sets: DecisionSet[] = opts.sets ?? [];
  let rows: DecisionExample[] = [];
  let run: TrainRun | null = null;
  const log: string[] = [];
  const answersOf = (s: DecisionSet) =>
    s.kind === "yes_no"
      ? ["yes", "no"]
      : s.kind === "score"
        ? Array.from({ length: s.levels }, (_, i) => String(i + 1))
        : s.options.map((o) => o.label);
  const problemOf = (s: DecisionSet) =>
    s.question.trim() === ""
      ? "Write the question it should answer about every text."
      : s.kind === "category" && s.options.length < 2
        ? "Give at least two categories, each with a name."
        : null;
  const view = (s: DecisionSet): DecisionSet => {
    const answers = answersOf(s);
    const plan = planFor(rows, s.rights, answers, problemOf(s));
    return {
      ...s,
      examples: rows.length,
      rows,
      plan,
      missing: plan.missing,
      answers,
      problem: problemOf(s),
    };
  };
  const base = (): DecisionSet => ({
    id: "s".repeat(32),
    name: "",
    kind: "yes_no",
    question: "",
    options: [],
    levels: 5,
    low: "",
    high: "",
    quality: "quick",
    base: "",
    rights: "",
    created_at: "",
    examples: 0,
    missing: null,
    steps: 20,
    estimate: "Under a minute",
  });
  const api = {
    decisionStatus: async () => ({ ...STATUS, ...opts.status }),
    decisionSetup: async () => {
      if (!opts.setup) throw new Error("no such component");
      return opts.setup;
    },
    installDecisionSetup: vi.fn(async () => ({
      ...OFFER,
      progress: { ...OFFER.progress, state: "installing" as const, total_bytes: 1_013_795_574 },
    })),
    cancelDecisionSetup: async () => OFFER,
    decisionBases: async () => [],
    decisionSets: async () => sets,
    createDecisionSet: async () => {
      log.push("create");
      const s = base();
      sets = [s];
      return view(s);
    },
    decisionSet: async () => view(sets[0] as DecisionSet),
    updateDecisionSet: async (_id: string, patch: Partial<DecisionSet>) => {
      log.push(`patch ${JSON.stringify(patch)}`);
      sets = sets.map((s) => ({ ...s, ...patch }));
      return view(sets[0] as DecisionSet);
    },
    setDecisionExamples: async (_id: string, next: DecisionExample[]) => {
      log.push(`examples ${next.length}`);
      rows = next;
      return view(sets[0] as DecisionSet);
    },
    removeDecisionSet: async () => {
      sets = [];
    },
    startDecisionRun: async () => {
      log.push("run");
      run = {
        id: "r".repeat(32),
        dataset_id: "s".repeat(32),
        status: "working",
        stage: "Learning, step 5 of 20",
        step: 5,
        steps: 20,
        progress: 0.25,
        error: null,
        base: "laya-english",
        samples: [],
        preview: false,
        model_id: null,
        elapsed_s: null,
        estimate: "Under a minute",
        live: true,
        created_at: "",
        finished_at: null,
      };
      return run;
    },
    run: async () => run as TrainRun,
    cancelRun: async () => {
      log.push("cancel");
      run = { ...(run as TrainRun), status: "cancelled", error: "Stopped." };
      return { cancelled: true };
    },
    model: async () => MODEL,
    askDecision: vi.fn(async (_id: string, text: string) => ({
      question: "Which team should handle this message?",
      kind: "category" as const,
      answers: ["billing", "bug", "other"],
      mine: said(text.includes("crash") ? "bug" : "billing", 0.91),
      original: said("other", 0.42),
    })),
    sortDecision: vi.fn(async (_id: string, texts: string[]) => ({
      question: "Which team should handle this message?",
      kind: "category" as const,
      answers: ["billing", "bug", "other"],
      results: texts.map((t) => said(t.includes("crash") ? "bug" : "billing", 0.88)),
    })),
  } as unknown as TrainingApi;
  return {
    api,
    log,
    finish: () => {
      run = { ...(run as TrainRun), status: "done", progress: 1, step: 20, model_id: MODEL.id };
    },
  };
}

describe("reading a table of texts and answers", () => {
  it("reads tab separated cells, as pasted from a spreadsheet", () => {
    expect(parseTable("Great!\tyes\nTerrible\tno\n\nno tab here\n\tmissing text")).toEqual([
      { text: "Great!", answer: "yes" },
      { text: "Terrible", answer: "no" },
    ]);
  });

  it("reads a CSV with quoted cells, a comma, a line break and a doubled quote", () => {
    const csv = 'text,label\n"Hello, world",yes\n"He said ""no""\nand left",no\nplain,yes\n';
    expect(parseCells(csv)).toEqual([
      ["text", "label"],
      ["Hello, world", "yes"],
      ['He said "no"\nand left', "no"],
      ["plain", "yes"],
    ]);
    // the row that names the columns is left out
    expect(parseTable(csv)).toEqual([
      { text: "Hello, world", answer: "yes" },
      { text: 'He said "no"\nand left', answer: "no" },
      { text: "plain", answer: "yes" },
    ]);
  });

  it("reads semicolons, a byte order mark and Windows line ends; the text is the first column and the answer the last", () => {
    expect(parseTable("\uFEFFtext;label\r\nGood one;yes\r\nBad one;no\r\n")).toEqual([
      { text: "Good one", answer: "yes" },
      { text: "Bad one", answer: "no" },
    ]);
    // a file with other columns between the two still works as the screen says
    expect(parseTable("Good one,note,yes\nBad one,note,no\n")).toEqual([
      { text: "Good one", answer: "yes" },
      { text: "Bad one", answer: "no" },
    ]);
  });
});

describe("Decide", () => {
  it("starts with no sets, makes one, and says what is missing before teaching", async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<Decide api={engine.api} pollMs={10} onBack={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "New set of examples" }));
    expect(await screen.findByText("1 The question")).toBeTruthy();
    expect(
      (await screen.findAllByText("Write the question it should answer about every text.")).length,
    ).toBeGreaterThan(0);
    expect((screen.getByRole("button", { name: "Teach it" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("asks for categories with their meaning and keeps them as they are typed", async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<Decide api={engine.api} pollMs={10} onBack={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "New set of examples" }));
    await user.click(await screen.findByRole("button", { name: "One of several" }));
    expect(await screen.findByText("The categories")).toBeTruthy();
    await user.click(screen.getByLabelText("Name of category 1"));
    await user.paste("billing");
    await user.click(screen.getByLabelText("What category 1 means"));
    await user.paste("money");
    await user.click(screen.getByLabelText("Name of category 2"));
    await user.paste("bug");
    await user.tab();
    await waitFor(() =>
      expect(
        engine.log.some((l) => l.includes('"options":[{"label":"billing","about":"money"}')),
      ).toBe(true),
    );
    await user.click(screen.getByRole("button", { name: "Add a category" }));
    expect(screen.getByLabelText("Name of category 3")).toBeTruthy();
    // a category can be taken away, but two stay
    await user.click(screen.getByRole("button", { name: "Remove category 3" }));
    expect(
      (screen.getByRole("button", { name: "Remove category 2" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("asks what the ends of a score mean", async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<Decide api={engine.api} pollMs={10} onBack={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "New set of examples" }));
    await user.click(await screen.findByRole("button", { name: "A score" }));
    expect(await screen.findByLabelText("What 1 means")).toBeTruthy();
    expect(screen.getByLabelText("What the top score means")).toBeTruthy();
    expect((screen.getByLabelText("The score goes from 1 to") as HTMLInputElement).value).toBe("5");
  });

  it(
    "pastes examples in, says whose they are, teaches, follows the run and shows the report",
    { timeout: 30_000 },
    async () => {
      const user = userEvent.setup();
      const engine = fake();
      render(<Decide api={engine.api} pollMs={10} onBack={() => {}} />);
      await user.click(await screen.findByRole("button", { name: "New set of examples" }));
      await user.click(await screen.findByLabelText("The question"));
      await user.paste("Is this review positive?");
      await user.tab();
      await user.click(await screen.findByText("Paste from a spreadsheet or open a file"));
      const lines = Array.from(
        { length: 24 },
        (_, i) => `Review ${i}\t${i % 2 ? "yes" : "no"}`,
      ).join("\n");
      await user.click(screen.getByLabelText(/Two columns/));
      await user.paste(lines);
      await user.click(screen.getByRole("button", { name: /Add 24 pasted rows/ }));
      expect(await screen.findByLabelText("The text, example 24")).toBeTruthy();
      expect(await screen.findByText("Say whose these texts are first.")).toBeTruthy();
      await user.click(screen.getByRole("button", { name: "They are mine" }));
      await waitFor(
        () =>
          expect(
            (screen.getByRole("button", { name: "Teach it" }) as HTMLButtonElement).disabled,
          ).toBe(false),
        { timeout: 3000 },
      );
      await user.click(screen.getByRole("button", { name: "Teach it" }));
      expect(await screen.findByText("25%")).toBeTruthy();
      // the examples were sent before the run started
      expect(engine.log.indexOf("examples 24")).toBeGreaterThanOrEqual(0);
      expect(engine.log.indexOf("examples 24")).toBeLessThan(engine.log.indexOf("run"));
      engine.finish();
      expect(await screen.findByText("Support messages is ready")).toBeTruthy();
      expect(screen.getByText("After it was taught")).toBeTruthy();
      expect(screen.getByText("11 of 12")).toBeTruthy();
    },
  );

  it("stops a run that is going", async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<Decide api={engine.api} pollMs={10} onBack={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "New set of examples" }));
    await user.click(await screen.findByLabelText("The question"));
    await user.paste("Is this good?");
    await user.tab();
    await user.click(await screen.findByText("Paste from a spreadsheet or open a file"));
    await user.click(screen.getByLabelText(/Two columns/));
    await user.paste(
      Array.from({ length: 22 }, (_, i) => `Text ${i}\t${i % 2 ? "yes" : "no"}`).join("\n"),
    );
    await user.click(screen.getByRole("button", { name: /Add 22 pasted rows/ }));
    await user.click(await screen.findByRole("button", { name: "I have permission to use them" }));
    await waitFor(
      () =>
        expect(
          (screen.getByRole("button", { name: "Teach it" }) as HTMLButtonElement).disabled,
        ).toBe(false),
      { timeout: 3000 },
    );
    await user.click(screen.getByRole("button", { name: "Teach it" }));
    await user.click(await screen.findByRole("button", { name: /Cancel/i }));
    expect(await screen.findByText("Stopped")).toBeTruthy();
    expect(engine.log).toContain("cancel");
  });

  it("keeps the model and method behind one closed line that says what is recommended", async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<Decide api={engine.api} pollMs={10} onBack={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "New set of examples" }));
    const summary = await screen.findByText("Choose the model and method");
    const box = summary.closest("details") as HTMLDetailsElement;
    expect(box.open).toBe(false);
    expect(within(summary).getByText("Recommended")).toBeTruthy();
    await user.click(within(box).getByRole("button", { name: "Better" }));
    expect(within(summary).getByText("Laya, Better")).toBeTruthy();
    // nothing about encoders, loss or calibration
    expect(screen.queryByText(/encoder|calibration|loss/i)).toBeNull();
  });

  it("offers to set up the trainer and the model, with the size, before anything is fetched", async () => {
    const user = userEvent.setup();
    const engine = fake({
      status: { ready: false, problem: "Training is not set up on this computer yet." },
      setup: OFFER,
    });
    render(<Decide api={engine.api} pollMs={10} onBack={() => {}} />);
    expect(await screen.findByText("Set up training")).toBeTruthy();
    expect(screen.getByText(/needs a trainer and a small model to learn on/)).toBeTruthy();
    expect(screen.getByText("Trainer (Laya and PyTorch)")).toBeTruthy();
    expect(engine.api.installDecisionSetup).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /Download and set up/ }));
    expect(engine.api.installDecisionSetup).toHaveBeenCalledWith(1_013_795_574);
  });

  it("says why it cannot run when the trainer is not set up", async () => {
    const engine = fake({
      status: {
        ready: false,
        problem: "Training is not set up on this computer yet. Set it up first.",
      },
    });
    render(<Decide api={engine.api} pollMs={10} onBack={() => {}} />);
    expect(await screen.findByText("Teaching it to decide is not ready")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "New set of examples" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});

describe("DecideResult", () => {
  it("shows how often it was right beside the untaught model and a word counter, and where it went wrong", async () => {
    const engine = fake();
    render(<DecideResult model={MODEL} api={engine.api} />);
    expect(screen.getByText("Support messages is ready")).toBeTruthy();
    const stats = screen.getByLabelText("How often it was right");
    expect(within(stats).getByText("11 of 12")).toBeTruthy();
    expect(within(stats).getByText("5 of 12")).toBeTruthy();
    expect(within(stats).getByText("9 of 12")).toBeTruthy();
    expect(screen.getByText(/right 10 of 10 times/)).toBeTruthy();
    expect(screen.getByText(/bug called other \(1 time\)/)).toBeTruthy();
    expect(screen.getAllByText(/right 4 of 4/)).toHaveLength(2);
    expect(screen.getByText("It froze when I paid")).toBeTruthy();
  });

  it("tries one text beside the model it started from", async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<DecideResult model={MODEL} api={engine.api} />);
    await user.click(screen.getByLabelText("Paste a text"));
    await user.paste("The app will crash again");
    await user.click(screen.getByRole("button", { name: "Decide" }));
    const got = await screen.findByLabelText("Its answer");
    expect(within(got).getByText("bug")).toBeTruthy();
    expect(within(got).getByText(/91% sure/)).toBeTruthy();
    expect(within(got).getByText("Before it was taught")).toBeTruthy();
    expect(engine.api.askDecision).toHaveBeenCalledWith(MODEL.id, "The app will crash again");
  });

  it("decides a list, one text a line, and copies the table", async () => {
    const user = userEvent.setup();
    const engine = fake();
    const write = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: write },
      configurable: true,
    });
    render(<DecideResult model={MODEL} api={engine.api} />);
    await user.click(screen.getByLabelText("One text on each line"));
    await user.paste("my invoice is wrong\nit will crash\n\nsecond refund please");
    await user.click(screen.getByRole("button", { name: "Decide 3 texts" }));
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByText("it will crash").closest("tr")?.textContent).toContain("bug");
    await user.click(screen.getByRole("button", { name: "Copy as a table" }));
    expect(write).toHaveBeenCalledWith(
      "my invoice is wrong\tbilling\t88%\nit will crash\tbug\t88%\nsecond refund please\tbilling\t88%",
    );
    expect(await screen.findByText("Copied. Paste it into a spreadsheet.")).toBeTruthy();
  });
});
