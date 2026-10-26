import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
// @vitest-environment jsdom
import type {
  LanguageBase,
  TrainRun,
  TrainedModel,
  TrainingApi,
  TrainingSetupState,
  WritingExample,
  WritingPlan,
  WritingSet,
  WritingStatus,
} from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatWithIt, Writing, parsePasted } from "./Writing";

afterEach(cleanup);

const STATUS: WritingStatus = {
  ready: true,
  problem: null,
  engine: {},
  fit: { verdict: "fits", reason: "" },
  busy: false,
  active_run: null,
  place: "device",
  min_examples: 10,
  good_examples: 50,
  rights: ["mine", "permission"],
  qualities: ["quick", "better"],
  choices: { family: "language", default_base: "q", default_method: "qlora", bases: [] },
  in_chat: null,
  bases: [],
};

function planFor(
  rows: WritingExample[],
  rights: string,
  baseMissing: string | null = null,
): WritingPlan {
  const n = rows.length;
  const missing =
    n < 10
      ? `Add at least 10 examples. You have ${n}. 50 or more is better.`
      : rights === ""
        ? "Say whose these examples are first."
        : baseMissing;
  return {
    examples: n,
    dropped: [],
    checks:
      n < 10
        ? [{ level: "error", code: "too_few", message: missing as string }]
        : [
            {
              level: "warn",
              code: "few",
              message: `Only ${n} examples: the result will mostly copy them. 50 or more is better.`,
            },
          ],
    steps: 30,
    estimate: "Under a minute",
    base: "qwen3-0.6b-4bit",
    base_title: "Qwen3 0.6B",
    base_note: "Small and quick: it picks up a style, not new facts.",
    held_back: 2,
    missing,
  };
}

const MODEL: TrainedModel = {
  id: "m".repeat(32),
  run_id: "r".repeat(32),
  dataset_id: "s".repeat(32),
  name: "My replies",
  trigger_word: "",
  kind: "writing",
  base: "qwen3-0.6b-4bit",
  preview: false,
  adapter_bytes: 100,
  created_at: "",
  card: {
    base_title: "Qwen3 0.6B",
    licence: "Apache-2.0",
    engine: "mlx-lm",
    preview: false,
    note: "",
    dataset: { name: "My replies", kind: "writing", examples: 12, hash: "h" },
    steps: 30,
    seconds: 9,
    trigger_word: "",
    statement: "",
    evaluation: {
      passed: true,
      note: "On 2 answers it had not seen, it got 52 percent closer to your answers.",
      at: "",
    },
    trained_at: "",
    answers: [
      {
        question: "How do I update the app?",
        before: "Go to the app store and look for updates.",
        after: "Open Settings and press Update. - Wasi",
      },
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
    bytes: 416_000_000,
    needs_free_bytes: 1_490_000_000,
    parts: [
      {
        name: "Trainer (mlx-lm)",
        version: "0.31.3",
        bytes: 64_300_000,
        have: false,
        licence: "MIT",
        source: "pypi.org",
      },
      {
        name: "Qwen3 0.6B (4-bit)",
        version: "the writing model it learns on",
        bytes: 351_400_000,
        have: false,
        licence: "Apache-2.0",
        source: "huggingface.co",
      },
    ],
  },
  progress: { state: "idle", step: null, steps: [], message: "", done_bytes: 0, total_bytes: 0 },
};

function fake(
  opts: {
    status?: Partial<WritingStatus>;
    sets?: WritingSet[];
    setup?: TrainingSetupState;
    baseMissing?: (base: string) => string | null;
  } = {},
) {
  let sets: WritingSet[] = opts.sets ?? [];
  let rows: WritingExample[] = [];
  let run: TrainRun | null = null;
  const log: string[] = [];
  const view = (s: WritingSet): WritingSet => ({
    ...s,
    examples: rows.length,
    rows,
    plan: planFor(rows, s.rights, opts.baseMissing?.(s.base) ?? null),
    missing: planFor(rows, s.rights, opts.baseMissing?.(s.base) ?? null).missing,
  });
  const base = (): WritingSet => ({
    id: "s".repeat(32),
    name: "",
    quality: "quick",
    base: "",
    rights: "",
    created_at: "",
    examples: 0,
    missing: null,
    steps: 30,
    estimate: "Under a minute",
  });
  const api = {
    writingStatus: async () => ({ ...STATUS, ...opts.status }),
    writingSetup: async () => {
      if (!opts.setup) throw new Error("no such component");
      return opts.setup;
    },
    installWritingSetup: vi.fn(async () => ({
      ...OFFER,
      progress: { ...OFFER.progress, state: "installing" as const, total_bytes: 416_000_000 },
    })),
    cancelWritingSetup: async () => OFFER,
    writingSets: async () => sets,
    createWritingSet: async () => {
      log.push("create");
      const s = base();
      sets = [s];
      return view(s);
    },
    writingSet: async () => view(sets[0] as WritingSet),
    updateWritingSet: async (_id: string, patch: Partial<WritingSet>) => {
      log.push(`patch ${JSON.stringify(patch)}`);
      sets = sets.map((s) => ({ ...s, ...patch }));
      return view(sets[0] as WritingSet);
    },
    setExamples: async (_id: string, next: WritingExample[]) => {
      log.push(`examples ${next.length}`);
      rows = next;
      return view(sets[0] as WritingSet);
    },
    removeWritingSet: async () => {
      sets = [];
    },
    startWritingRun: async () => {
      log.push("run");
      run = {
        id: "r".repeat(32),
        dataset_id: "s".repeat(32),
        status: "working",
        stage: "Learning, step 5 of 30",
        step: 5,
        steps: 30,
        progress: 5 / 30,
        error: null,
        base: "q",
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
    askWriting: vi.fn(async (_id: string, question: string) => ({
      question,
      original: "It depends on the models.",
      mine: "Yes, switch them on your own. - Wasi",
    })),
  } as unknown as TrainingApi;
  return {
    api,
    log,
    finish: () => {
      run = { ...(run as TrainRun), status: "done", progress: 1, step: 30, model_id: MODEL.id };
    },
  };
}

/** Add `n` examples: pasted into the two boxes (typing key by key made this test slower than a busy CI runner allows). */
const typed = async (user: ReturnType<typeof userEvent.setup>, n: number) => {
  for (let i = 0; i < n; i++) {
    await user.click(screen.getByRole("button", { name: "Add an example" }));
    await user.click(screen.getByLabelText(`What it is asked, example ${i + 1}`));
    await user.paste(`Question ${i}?`);
    await user.click(screen.getByLabelText(`What it should answer, example ${i + 1}`));
    await user.paste(`Answer ${i}. - Wasi`);
  }
};

describe("Writing", () => {
  it("reads rows pasted from a spreadsheet: a question and an answer between a tab", () => {
    expect(parsePasted("Q1?\tA1\nQ2?\tA2 more\n\nno tab here\n\tmissing question")).toEqual([
      { ask: "Q1?", answer: "A1" },
      { ask: "Q2?", answer: "A2 more" },
    ]);
  });

  it("starts with no sets, makes one, and says what is missing before teaching", async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<Writing api={engine.api} pollMs={10} onBack={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "New set of examples" }));
    expect(
      await screen.findByText("Add at least 10 examples. You have 0. 50 or more is better.", {
        selector: "p, div",
      }),
    ).toBeTruthy();
    expect((screen.getByRole("button", { name: "Teach it" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it(
    "teaches from typed examples, follows the run and shows the answers before and after",
    { timeout: 30_000 },
    async () => {
      const user = userEvent.setup();
      const engine = fake();
      render(<Writing api={engine.api} pollMs={10} onBack={() => {}} />);
      await user.click(await screen.findByRole("button", { name: "New set of examples" }));
      await user.click(await screen.findByRole("button", { name: "Add an example" }));
      // a row can be added, typed into and removed
      await user.type(screen.getByLabelText("What it is asked, example 1"), "Gone?");
      await user.click(screen.getByRole("button", { name: "Remove example 1" }));
      await typed(user, 10);
      // rights are asked for: nothing starts until they are said
      await waitFor(
        () => expect(screen.getByText("Say whose these examples are first.")).toBeTruthy(),
        { timeout: 3000 },
      );
      await user.click(screen.getByRole("button", { name: "I wrote these" }));
      await waitFor(
        () =>
          expect(
            (screen.getByRole("button", { name: "Teach it" }) as HTMLButtonElement).disabled,
          ).toBe(false),
        { timeout: 3000 },
      );
      expect(screen.getByText(/It is taught on Qwen3 0.6B: Small and quick/)).toBeTruthy();
      await user.click(screen.getByRole("button", { name: "Teach it" }));
      expect(await screen.findByText("17%")).toBeTruthy();
      // the typed examples were sent before the run started
      expect(engine.log.indexOf("examples 10")).toBeGreaterThanOrEqual(0);
      expect(engine.log.indexOf("examples 10")).toBeLessThan(engine.log.indexOf("run"));
      engine.finish();
      expect(await screen.findByText("My replies is ready")).toBeTruthy();
      expect(screen.getByText(/52 percent closer/)).toBeTruthy();
      expect(screen.getByText("Go to the app store and look for updates.")).toBeTruthy();
      expect(screen.getByText("Open Settings and press Update. - Wasi")).toBeTruthy();
      await user.type(screen.getByLabelText("Ask both something new"), "Can I use two models?");
      await user.click(screen.getByRole("button", { name: "Ask both" }));
      const both = await screen.findByLabelText("Its answers");
      expect(within(both).getByText("It depends on the models.")).toBeTruthy();
      expect(within(both).getByText("Yes, switch them on your own. - Wasi")).toBeTruthy();
    },
  );

  it("keeps the model and method behind one closed line that says what is recommended", async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<Writing api={engine.api} pollMs={10} onBack={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "New set of examples" }));
    const summary = await screen.findByText("Choose the model and method");
    const box = summary.closest("details") as HTMLDetailsElement;
    expect(box.open).toBe(false);
    expect(within(summary).getByText("Recommended")).toBeTruthy();
    // nothing writing-specific on the front door of the screen
    expect(screen.queryByText(/write like me/i)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Add an example" }));
    expect(screen.getByLabelText("What it is asked, example 1")).toBeTruthy();
    expect(screen.getByLabelText("What it should answer, example 1")).toBeTruthy();
    await user.click(within(box).getByRole("button", { name: "Better" }));
    expect(within(summary).getByText("Qwen3 0.6B, Better")).toBeTruthy();
  });

  it("pastes rows in and stops a run that is going", { timeout: 30_000 }, async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<Writing api={engine.api} pollMs={10} onBack={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "New set of examples" }));
    await user.click(await screen.findByText("Paste from a spreadsheet"));
    const rows = Array.from({ length: 12 }, (_, i) => `Q${i}?\tA${i}`).join("\n");
    await user.click(screen.getByLabelText(/Two columns/));
    await user.paste(rows);
    await user.click(screen.getByRole("button", { name: /Add 12 pasted rows/ }));
    expect(await screen.findByLabelText("What it is asked, example 12")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "I have permission to use them" }));
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

  it("offers to set up the trainer and the small model, with the size, before anything is fetched", async () => {
    const user = userEvent.setup();
    const engine = fake({
      status: { ready: false, problem: "Training is not set up on this computer yet." },
      setup: OFFER,
    });
    render(<Writing api={engine.api} pollMs={10} onBack={() => {}} />);
    expect(await screen.findByText("Set up training")).toBeTruthy();
    expect(screen.getByText(/needs a trainer and a small model to learn on/)).toBeTruthy();
    expect(screen.getByText("Trainer (mlx-lm)")).toBeTruthy();
    expect(screen.getByText(/Qwen3 0.6B \(4-bit\)/)).toBeTruthy();
    expect(engine.api.installWritingSetup).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /Download and set up/ }));
    expect(engine.api.installWritingSetup).toHaveBeenCalledWith(416_000_000);
  });

  it("says why it cannot run when the trainer is not set up", async () => {
    const engine = fake({
      status: {
        ready: false,
        problem: "Training is not set up on this computer yet. Set it up first.",
      },
    });
    render(<Writing api={engine.api} pollMs={10} onBack={() => {}} />);
    expect(await screen.findByText("Teaching a writing model is not ready")).toBeTruthy();
    expect(screen.getByText(/Set it up first/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "New set of examples" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});

const PART = (bytes: number, title: string, have: boolean) => ({
  have,
  bytes: have ? 0 : bytes,
  title,
  needs_free_bytes: have ? 0 : bytes + 1_073_741_824,
  progress: { state: "idle" as const, message: "", done_bytes: 0, total_bytes: 0 },
});

const base = (
  id: string,
  title: string,
  train: number,
  chat: number,
  have: boolean,
): LanguageBase => ({
  id,
  title,
  licence: "Apache-2.0",
  source: "huggingface.co",
  main: id === "qwen3-0.6b-4bit",
  problem: null,
  model: PART(train, title, have),
  chat: PART(chat, `${title} for chat`, false),
});

/** The language side of the engine: which bases are on this computer, and which model chat uses. */
function chatFake(start: { have: boolean; inChat?: string | null }) {
  const now = {
    bases: [base("qwen3-0.6b-4bit", "Qwen3 0.6B", 351_000_000, 639_446_688, true)],
    inChat: start.inChat ?? null,
  };
  now.bases[0] = {
    ...now.bases[0],
    chat: PART(639_446_688, "Qwen3 0.6B for chat (8-bit)", start.have),
  } as LanguageBase;
  const api = {
    writingStatus: async () => ({ ...STATUS, in_chat: now.inChat, bases: now.bases }),
    languageBases: async () => now.bases,
    installLanguagePart: vi.fn(async (id: string, part: "model" | "chat") => {
      now.bases = now.bases.map((b) =>
        b.id === id
          ? {
              ...b,
              [part]: {
                ...b[part],
                progress: {
                  state: "installing" as const,
                  message: "Downloading",
                  done_bytes: 100,
                  total_bytes: b[part].bytes,
                },
              },
            }
          : b,
      );
      return now.bases;
    }),
    cancelLanguagePart: async () => now.bases,
    useWritingInChat: vi.fn(async (id: string) => {
      now.inChat = id;
    }),
    stopWritingInChat: vi.fn(async () => {
      now.inChat = null;
      return { ended: true };
    }),
  } as unknown as TrainingApi;
  return { api, now };
}

describe("Chat with it", () => {
  it("asks for the chat form of the model first, with its size, and fetches nothing until pressed", async () => {
    const user = userEvent.setup();
    const { api, now } = chatFake({ have: false });
    render(<ChatWithIt model={MODEL} api={api} pollMs={10} />);
    expect(await screen.findByText(/the same model in the form its chat engine runs/)).toBeTruthy();
    expect(
      screen.getByText(/Qwen3 0.6B for chat \(8-bit\), 639 MB, Apache-2.0, from huggingface.co/),
    ).toBeTruthy();
    expect(api.installLanguagePart).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /Download \(639 MB\) and use in chat/ }));
    expect(api.installLanguagePart).toHaveBeenCalledWith("qwen3-0.6b-4bit", "chat", 639_446_688);
    expect((await screen.findAllByText("Getting the model for chat")).length).toBeGreaterThan(0);
    // when it is there the button to use it appears
    now.bases = now.bases.map((b) => ({
      ...b,
      chat: { ...b.chat, have: true, progress: { ...b.chat.progress, state: "ready" as const } },
    }));
    expect(await screen.findByRole("button", { name: "Use in chat" })).toBeTruthy();
  });

  it("uses the model in chat, says so, and goes back to the model chosen before", async () => {
    const user = userEvent.setup();
    const { api } = chatFake({ have: true });
    render(<ChatWithIt model={MODEL} api={api} pollMs={10} />);
    expect(screen.queryByText(/same model in the form/)).toBeNull();
    await user.click(await screen.findByRole("button", { name: "Use in chat" }));
    expect(api.useWritingInChat).toHaveBeenCalledWith(MODEL.id);
    expect(await screen.findByText(/Chat answers with this model now/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Back to my chat model" }));
    expect(api.stopWritingInChat).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Use in chat" })).toBeTruthy();
  });

  it("offers to switch when chat uses another taught model", async () => {
    const { api } = chatFake({ have: true, inChat: "x".repeat(32) });
    render(<ChatWithIt model={MODEL} api={api} pollMs={10} />);
    expect(
      await screen.findByRole("button", { name: "Use this one in chat instead" }),
    ).toBeTruthy();
  });
});

const ROW = (id: string, title: string, installed: boolean, recommended = false) => ({
  id,
  title,
  licence: "Apache-2.0",
  engine: "mlx-lm",
  recommended,
  can_teach: true,
  reason: "",
  installed,
  note: `${title} note.`,
  measured: installed ? "70 steps in 13 s" : "",
  methods: [
    {
      id: "qlora" as const,
      title: "Small adapter, less memory",
      technical: "QLoRA",
      advanced: false,
      can: true,
      reason: "",
    },
  ],
});

describe("Which model?", () => {
  it(
    "lists the models, fetches one that is not there after its size is shown, and teaching waits for it",
    { timeout: 30_000 },
    async () => {
      const user = userEvent.setup();
      const installed = new Set(["qwen3-0.6b-4bit"]);
      const engine = fake({
        baseMissing: (b) =>
          installed.has(b || "qwen3-0.6b-4bit")
            ? null
            : "Qwen3 1.7B is not on this computer yet. Get it first, next to its name.",
      });
      const choices = () => ({
        family: "language",
        default_base: "qwen3-0.6b-4bit",
        default_method: "qlora" as const,
        bases: [
          ROW("qwen3-0.6b-4bit", "Qwen3 0.6B", installed.has("qwen3-0.6b-4bit"), true),
          ROW("qwen3-1.7b-4bit", "Qwen3 1.7B", installed.has("qwen3-1.7b-4bit")),
        ],
      });
      let getting = false;
      const parts = () => {
        const big = base(
          "qwen3-1.7b-4bit",
          "Qwen3 1.7B",
          984_000_000,
          1_834_000_000,
          installed.has("qwen3-1.7b-4bit"),
        );
        if (getting && !big.model.have) {
          big.model.progress = {
            state: "installing",
            message: "Downloading",
            done_bytes: 100,
            total_bytes: 984_000_000,
          };
        }
        return [base("qwen3-0.6b-4bit", "Qwen3 0.6B", 351_000_000, 639_000_000, true), big];
      };
      engine.api.writingStatus = async () => ({ ...STATUS, choices: choices() }) as WritingStatus;
      engine.api.languageBases = async () => parts();
      const update = vi.spyOn(engine.api, "updateWritingSet");
      engine.api.installLanguagePart = vi.fn(async () => {
        getting = true;
        return parts();
      }) as unknown as TrainingApi["installLanguagePart"];
      render(<Writing api={engine.api} pollMs={10} onBack={() => {}} />);
      await user.click(await screen.findByRole("button", { name: "New set of examples" }));
      await user.click(await screen.findByText("Paste from a spreadsheet"));
      await user.click(screen.getByLabelText(/Two columns/));
      await user.paste(Array.from({ length: 12 }, (_, i) => `Q${i}?\tA${i}`).join("\n"));
      await user.click(screen.getByRole("button", { name: /Add 12 pasted rows/ }));
      await user.click(await screen.findByRole("button", { name: "I wrote these" }));
      expect(await screen.findByText("Which model?")).toBeTruthy();
      expect((screen.getByLabelText("Qwen3 0.6B") as HTMLInputElement).checked).toBe(true);
      expect(screen.getByText(/Measured here: 70 steps in 13 s/)).toBeTruthy();
      // nothing to get for the model that is there; the other one says its size
      expect(screen.queryByRole("button", { name: "Get Qwen3 0.6B" })).toBeNull();
      const get = await screen.findByRole("button", { name: "Get Qwen3 1.7B" });
      expect(get.textContent).toBe("Get it (984 MB)");
      // choosing it: teaching waits and says why
      await user.click(screen.getByLabelText("Qwen3 1.7B"));
      expect(update).toHaveBeenCalledWith(expect.any(String), { base: "qwen3-1.7b-4bit" });
      expect(await screen.findByText(/Qwen3 1.7B is not on this computer yet/)).toBeTruthy();
      expect((screen.getByRole("button", { name: "Teach it" }) as HTMLButtonElement).disabled).toBe(
        true,
      );
      // fetching it: the size was shown on the button and is sent back
      await user.click(get);
      expect(engine.api.installLanguagePart).toHaveBeenCalledWith(
        "qwen3-1.7b-4bit",
        "model",
        984_000_000,
      );
      // when it has arrived the plan is read again and teaching is possible
      installed.add("qwen3-1.7b-4bit");
      await waitFor(
        () =>
          expect(
            (screen.getByRole("button", { name: "Teach it" }) as HTMLButtonElement).disabled,
          ).toBe(false),
        { timeout: 4000 },
      );
    },
  );
});
