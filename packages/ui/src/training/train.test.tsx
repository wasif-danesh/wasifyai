import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
// @vitest-environment jsdom
import type {
  TrainChoices,
  TrainDataset,
  TrainPicture,
  TrainRun,
  TrainStatus,
  TrainedModel,
  TrainingApi,
} from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Train } from "./Train";

afterEach(cleanup);

const METHODS = (can: Record<string, string>): TrainChoices["bases"][number]["methods"] => [
  { id: "lora", title: "Small adapter", technical: "LoRA", advanced: false, can: true, reason: "" },
  {
    id: "qlora",
    title: "Small adapter, less memory",
    technical: "QLoRA",
    advanced: false,
    can: !can.qlora,
    reason: can.qlora ?? "",
  },
  {
    id: "full",
    title: "Teach all of it",
    technical: "full fine-tuning",
    advanced: true,
    can: !can.full,
    reason: can.full ?? "",
  },
];

const CHOICES: TrainChoices = {
  family: "image",
  default_base: "base-a",
  default_method: "lora",
  bases: [
    {
      id: "base-a",
      title: "Base A",
      licence: "Apache-2.0",
      engine: "mflux",
      recommended: true,
      can_teach: true,
      reason: "",
      installed: true,
      methods: METHODS({ qlora: "Pictures are taught as a small adapter." }),
    },
    {
      id: "base-b",
      title: "Base B",
      licence: "Apache-2.0",
      engine: "mflux",
      recommended: false,
      can_teach: true,
      reason: "",
      installed: true,
      methods: METHODS({ qlora: "Not for pictures.", full: "Needs far more memory." }),
    },
    {
      id: "",
      title: "Some other picture model",
      licence: "",
      engine: "",
      recommended: false,
      can_teach: false,
      reason: "This model cannot be taught yet: the app has no way to teach it.",
      installed: true,
      methods: [],
    },
  ],
};

const STATUS: TrainStatus = {
  ready: true,
  problem: null,
  preview: true,
  engine: {},
  fit: { verdict: "fits", reason: "" },
  busy: false,
  active_run: null,
  place: "device",
  min_pictures: 3,
  max_pictures: 100,
  kinds: ["character", "style", "object"],
  statements: {
    mine: "It's me",
    permission: "I have permission",
    drawing: "It's a drawing, a character or an animal",
    artwork: "It's my own artwork",
  },
  base: "flux2-klein-base-4b",
  steps: { character: 200, style: 250, object: 150 },
  estimates: {
    character: "About 25 minutes",
    style: "About 31 minutes",
    object: "About 19 minutes",
  },
};

/** An engine in memory: one set, its pictures and descriptions, one run that finishes when told to. */
function fake(over: Partial<TrainStatus> = {}) {
  const status = { ...STATUS, ...over };
  let set: TrainDataset | null = null;
  let items: TrainPicture[] = [];
  let run: TrainRun | null = null;
  let models: TrainedModel[] = [];
  const log: string[] = [];
  const dataset = (): TrainDataset => {
    const d = set as TrainDataset;
    const missing =
      items.length < status.min_pictures
        ? `Add at least ${status.min_pictures} pictures. 15 to 25 good ones is plenty.`
        : !d.rights
          ? "Say whose it is first."
          : !d.trigger_word
            ? "Choose the magic word first."
            : items.some((i) => !["done", "edited"].includes(i.caption_state))
              ? "Write the descriptions first."
              : null;
    return {
      ...d,
      pictures: items.length,
      missing,
      writing: false,
      items,
      suggestions: ["marlo", "zebrik", "kolan"],
    };
  };
  const api: TrainingApi = {
    status: async () => ({ ...status, busy: run?.status === "working", active_run: null }),
    choices: async () => CHOICES,
    datasets: async () => (set ? [dataset()] : []),
    createDataset: async (kind, name = "") => {
      log.push("create");
      set = {
        id: "d".repeat(32),
        kind,
        name,
        trigger_word: "",
        rights: "",
        created_at: "",
        pictures: 0,
        missing: null,
        writing: false,
      };
      return dataset();
    },
    dataset: async () => dataset(),
    updateDataset: async (_id, change) => {
      set = { ...(set as TrainDataset), ...change };
      return dataset();
    },
    removeDataset: async () => {
      set = null;
      items = [];
    },
    addPicture: async (_id, file, name = "") => {
      const small = name.startsWith("small");
      const item: TrainPicture = {
        id: `${items.length + 1}`.padStart(32, "0"),
        dataset_id: "d".repeat(32),
        name,
        width: 640,
        height: 640,
        checks: small
          ? [{ code: "too_small", level: "warn", message: "Too small: 300 by 300." }]
          : [{ code: "good", level: "ok", message: "Good." }],
        caption: "",
        caption_state: "none",
        caption_error: null,
        suggest_remove: small,
        created_at: "",
      };
      items = [...items, item];
      void file;
      return item;
    },
    removePicture: async (_d, id) => {
      items = items.filter((i) => i.id !== id);
    },
    editCaption: async (_d, id, caption) => {
      items = items.map((i) => (i.id === id ? { ...i, caption, caption_state: "edited" } : i));
      return items.find((i) => i.id === id) as TrainPicture;
    },
    writeCaptions: async (_d, o) => {
      const only = o?.pictureIds;
      items = items.map((i) =>
        (only ? only.includes(i.id) : i.caption_state === "none")
          ? { ...i, caption: "Standing on a beach.", caption_state: "done" }
          : i,
      );
      return { writing: items.length };
    },
    pictureUrl: async (_d, id) => `blob:${id}`,
    startRun: async (id) => {
      log.push("run");
      run = {
        id: "r".repeat(32),
        dataset_id: id,
        status: "working",
        stage: "Preview",
        step: 10,
        steps: 200,
        progress: 0.05,
        error: null,
        base: "b",
        samples: [],
        preview: status.preview,
        model_id: null,
        elapsed_s: null,
        estimate: "About 25 minutes",
        live: true,
        created_at: "",
        finished_at: null,
      };
      return run;
    },
    runs: async () => (run ? [run] : []),
    run: async () => run as TrainRun,
    cancelRun: async () => {
      run = { ...(run as TrainRun), status: "cancelled", error: "Stopped." };
      return { cancelled: true };
    },
    sampleUrl: async (_r, name) => `blob:${name}`,
    models: async () => models,
    model: async (id) => models.find((m) => m.id === id) as TrainedModel,
    renameModel: async (id, name) => {
      models = models.map((m) => (m.id === id ? { ...m, name } : m));
      return models.find((m) => m.id === id) as TrainedModel;
    },
    removeModel: async (id) => {
      models = models.filter((m) => m.id !== id);
    },
    pauseRun: async () => {
      run = { ...(run as TrainRun), status: "paused", stage: "Paused at step 10 of 200" };
      return { paused: true };
    },
    resumeRun: async () => {
      log.push("resume");
      run = { ...(run as TrainRun), status: "working", stage: "Starting again" };
      return run;
    },
    checkPlan: async () => ({ items: [], refs: 0 }),
    judge: async () => ({ same: true, reason: "" }),
    saveEvaluation: async (id) => models.find((m) => m.id === id) as TrainedModel,
    // no trainer component here (the web): nothing to set up
    setup: async () => {
      throw new Error("not available");
    },
    installSetup: async () => {
      throw new Error("not available");
    },
    cancelSetup: async () => {
      throw new Error("not available");
    },
    // the writing screen has its own tests (writing.test.tsx)
    useWritingInChat: async () => {
      throw new Error("not in this test");
    },
    stopWritingInChat: async () => ({ ended: false }),
    languageBases: async () => [],
    installLanguagePart: async () => {
      throw new Error("not in this test");
    },
    cancelLanguagePart: async () => {
      throw new Error("not in this test");
    },
    writingSetup: async () => {
      throw new Error("not in this test");
    },
    installWritingSetup: async () => {
      throw new Error("not in this test");
    },
    cancelWritingSetup: async () => {
      throw new Error("not in this test");
    },
    removeWritingSetup: async () => {
      throw new Error("not in this test");
    },
    writingStatus: async () => {
      throw new Error("not in this test");
    },
    writingSets: async () => [],
    createWritingSet: async () => {
      throw new Error("not in this test");
    },
    writingSet: async () => {
      throw new Error("not in this test");
    },
    updateWritingSet: async () => {
      throw new Error("not in this test");
    },
    setExamples: async () => {
      throw new Error("not in this test");
    },
    removeWritingSet: async () => {},
    startWritingRun: async () => {
      throw new Error("not in this test");
    },
    askWriting: async () => {
      throw new Error("not in this test");
    },
    // the decision screen has its own tests (decide.test.tsx)
    decisionSetup: async () => {
      throw new Error("not in this test");
    },
    installDecisionSetup: async () => {
      throw new Error("not in this test");
    },
    cancelDecisionSetup: async () => {
      throw new Error("not in this test");
    },
    removeDecisionSetup: async () => {
      throw new Error("not in this test");
    },
    decisionStatus: async () => {
      throw new Error("not in this test");
    },
    decisionSets: async () => [],
    createDecisionSet: async () => {
      throw new Error("not in this test");
    },
    decisionSet: async () => {
      throw new Error("not in this test");
    },
    updateDecisionSet: async () => {
      throw new Error("not in this test");
    },
    setDecisionExamples: async () => {
      throw new Error("not in this test");
    },
    removeDecisionSet: async () => {},
    startDecisionRun: async () => {
      throw new Error("not in this test");
    },
    askDecision: async () => {
      throw new Error("not in this test");
    },
    sortDecision: async () => {
      throw new Error("not in this test");
    },
    decisionBases: async () => [],
    installDecisionBase: async () => {
      throw new Error("not in this test");
    },
    cancelDecisionBase: async () => {
      throw new Error("not in this test");
    },
    removeSetup: async () => {
      throw new Error("not available");
    },
  };
  return {
    api,
    log,
    /** a run the app left paused: it is there when the screen opens */
    leavePaused() {
      run = {
        id: "r".repeat(32),
        dataset_id: "d".repeat(32),
        status: "paused",
        stage: "Paused at step 75 of 200",
        step: 75,
        steps: 200,
        progress: 0.37,
        error: null,
        base: "b",
        samples: [],
        preview: false,
        model_id: null,
        elapsed_s: null,
        estimate: "About 25 minutes",
        live: false,
        created_at: "",
        finished_at: null,
      };
    },
    finish() {
      models = [
        {
          id: "m".repeat(32),
          run_id: "r".repeat(32),
          dataset_id: null,
          name: "Marlo",
          trigger_word: "marlo",
          kind: "character",
          base: "b",
          preview: true,
          adapter_bytes: 4,
          created_at: "",
          card: {
            base_title: "FLUX.2 klein base 4B",
            licence: "Apache-2.0",
            engine: "preview",
            preview: true,
            note: "A preview: this file is not a trained model.",
            dataset: { name: "Marlo", kind: "character", pictures: 3, hash: "x" },
            steps: 200,
            seconds: 5,
            trigger_word: "marlo",
            statement: "x",
            evaluation: { passed: null, note: "" },
            trained_at: "",
          },
        },
      ];
      run = {
        ...(run as TrainRun),
        status: "done",
        progress: 1,
        step: 200,
        samples: ["step-0050.png"],
        model_id: models[0]?.id ?? null,
        preview: true,
      };
    },
    seed(m: TrainedModel[]) {
      models = m;
    },
  };
}

const file = (name: string) =>
  new File([new Uint8Array([137, 80, 78, 71])], name, { type: "image/png" });

describe("Train", () => {
  it("opens on four cards, says it is a preview, and the picture, writing and decision cards are live", async () => {
    const { api } = fake();
    render(<Train api={api} pollMs={10} />);
    expect(await screen.findByText("A preview")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Make my own character or style" })).toBeTruthy();
    expect(screen.queryByText(/Coming next/)).toBeNull();
    expect(
      screen.getByRole("button", { name: /Start: teach it from examples/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Teach it to decide" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start: teach it to decide/ })).toBeInTheDocument();
    // each card says which kind of model it trains, and the video one says what it needs
    for (const label of [
      "Image model training",
      "Language model training",
      "Decision model training",
      "Video model training",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText(/Needs an NVIDIA graphics card/)).toBeInTheDocument();
    expect(screen.getByText("Coming later")).toBeInTheDocument();
    expect((screen.getByRole("button", { name: "Start" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
    expect(screen.getByText("Nothing taught yet.")).toBeTruthy();
  });

  it("does not offer Start when the trainer is not ready, and says why", async () => {
    const { api } = fake({ ready: false, problem: "Not enough free disk space." });
    render(<Train api={api} pollMs={10} />);
    expect(await screen.findByText("Not enough free disk space.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Start" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("takes pictures, says what is wrong with each, and suggests removing the bad ones", async () => {
    const user = userEvent.setup();
    const { api } = fake();
    render(<Train api={api} pollMs={10} />);
    await user.click(await screen.findByRole("button", { name: "Start" }));
    const input = await screen.findByLabelText("Choose pictures");
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
    await user.upload(input, [file("a.png"), file("small.png")]);
    expect(await screen.findByText("Too small: 300 by 300.")).toBeTruthy();
    expect(screen.getByText(/2 pictures\. 1 with a problem/)).toBeTruthy();
    expect(screen.getByText("Add at least 3 pictures (1 more).")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Remove the 1 with a problem" }));
    await waitFor(() => expect(screen.getByText(/1 picture\. All good/)).toBeTruthy());
    await user.upload(input, [file("b.png"), file("c.png")]);
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(
        false,
      ),
    );
  });

  it("walks through Check to a finished model, in the person's words", async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<Train api={engine.api} pollMs={10} />);
    await user.click(await screen.findByRole("button", { name: "Start" }));
    await user.upload(await screen.findByLabelText("Choose pictures"), [
      file("a.png"),
      file("b.png"),
      file("c.png"),
    ]);
    await user.click(await screen.findByRole("button", { name: "Next" }));
    // nothing can be taught yet, and the screen says what is missing
    const teach = await screen.findByRole("button", { name: "Teach it" });
    expect((teach as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Say whose it is first.")).toBeTruthy();
    await user.click(screen.getByLabelText("It's a drawing, a character or an animal"));
    expect(await screen.findByText("Choose the magic word first.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "marlo" }));
    expect(await screen.findByText("Write the descriptions first.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /Write the descriptions \(3\)/ }));
    await waitFor(() =>
      expect(screen.getAllByDisplayValue("Standing on a beach.")).toHaveLength(3),
    );
    expect(await screen.findByText(/About 25 minutes\. Chat and image making pause/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Teach it" }));
    expect(await screen.findByText("Step 10 of 200")).toBeTruthy();
    engine.finish();
    expect(await screen.findByText("Marlo is ready")).toBeTruthy();
    expect(screen.getByText(/Nothing was learnt/)).toBeTruthy();
    expect(screen.getByText("marlo", { selector: "code" })).toBeTruthy();
    expect(await screen.findByAltText("Sample step-0050.png")).toBeTruthy();
  });

  /** Pictures in, rights and word chosen, descriptions written: the Teach it button is ready. */
  async function readyToTeach(user: ReturnType<typeof userEvent.setup>, api: TrainingApi) {
    render(<Train api={api} pollMs={10} />);
    await user.click(await screen.findByRole("button", { name: "Start" }));
    await user.upload(await screen.findByLabelText("Choose pictures"), [
      file("a.png"),
      file("b.png"),
      file("c.png"),
    ]);
    await user.click(await screen.findByRole("button", { name: "Next" }));
    await user.click(await screen.findByLabelText("It's a drawing, a character or an animal"));
    await user.click(await screen.findByRole("button", { name: "marlo" }));
    await user.click(await screen.findByRole("button", { name: /Write the descriptions \(3\)/ }));
    await waitFor(() =>
      expect(screen.getAllByDisplayValue("Standing on a beach.")).toHaveLength(3),
    );
  }

  it("teaches the recommendation when the choice is left closed", async () => {
    const user = userEvent.setup();
    const engine = fake();
    const start = vi.spyOn(engine.api, "startRun");
    await readyToTeach(user, engine.api);
    expect(await screen.findByText("Choose the model and method")).toBeTruthy();
    expect(screen.getAllByText("Recommended").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Teach it" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("d".repeat(32), {}));
  });

  it("lists what can be chosen with the reason for what cannot, and sends the choice", async () => {
    const user = userEvent.setup();
    const engine = fake();
    const start = vi.spyOn(engine.api, "startRun");
    await readyToTeach(user, engine.api);
    await user.click(await screen.findByText("Choose the model and method"));
    // a model nobody can teach is listed with the reason, and cannot be picked
    const other = screen.getByLabelText(/Some other picture model/) as HTMLInputElement;
    expect(other.disabled).toBe(true);
    expect(
      screen.getByText(/The app has no way to teach it|the app has no way to teach it/i),
    ).toBeTruthy();
    // a method the model cannot use is shown with why, not hidden
    const less = screen.getByLabelText(/Small adapter, less memory/) as HTMLInputElement;
    expect(less.disabled).toBe(true);
    expect(screen.getByText("Pictures are taught as a small adapter.")).toBeTruthy();
    // the technical name comes second, and teaching all of it sits under "For experts"
    expect(screen.getByText("(LoRA)")).toBeTruthy();
    await user.click(screen.getByText("For experts"));
    await user.click(screen.getByLabelText(/Teach all of it/));
    await user.click(screen.getByRole("button", { name: "Teach it" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("d".repeat(32), { method: "full" }));
  });

  it("starts a chosen model from its own recommendation", async () => {
    const user = userEvent.setup();
    const engine = fake();
    const start = vi.spyOn(engine.api, "startRun");
    await readyToTeach(user, engine.api);
    await user.click(await screen.findByText("Choose the model and method"));
    await user.click(screen.getByText("For experts"));
    await user.click(screen.getByLabelText(/Teach all of it/));
    await user.click(screen.getByLabelText(/Base B/));
    // Base B cannot teach all of it: the choice falls back to the small adapter
    expect((screen.getByLabelText(/Teach all of it/) as HTMLInputElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "Teach it" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("d".repeat(32), { base: "base-b" }));
  });

  it("lets the person change a description and describe one again", async () => {
    const user = userEvent.setup();
    const { api } = fake();
    render(<Train api={api} pollMs={10} />);
    await user.click(await screen.findByRole("button", { name: "Start" }));
    await user.upload(await screen.findByLabelText("Choose pictures"), [
      file("a.png"),
      file("b.png"),
      file("c.png"),
    ]);
    await user.click(await screen.findByRole("button", { name: "Next" }));
    await user.click(await screen.findByRole("button", { name: /Write the descriptions/ }));
    const box = await screen.findByLabelText("Description of a.png");
    await user.clear(box);
    await user.type(box, "On a hill.");
    await user.tab();
    expect(await screen.findByText("Changed by you.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Describe again a.png" }));
    await waitFor(() =>
      expect((screen.getByLabelText("Description of a.png") as HTMLTextAreaElement).value).toBe(
        "Standing on a beach.",
      ),
    );
  });

  it("stops a run that is going and says nothing was kept", async () => {
    const user = userEvent.setup();
    const engine = fake();
    render(<Train api={engine.api} pollMs={10} />);
    await user.click(await screen.findByRole("button", { name: "Start" }));
    await user.upload(await screen.findByLabelText("Choose pictures"), [
      file("a.png"),
      file("b.png"),
      file("c.png"),
    ]);
    await user.click(await screen.findByRole("button", { name: "Next" }));
    await user.click(screen.getByLabelText("It's me"));
    await user.click(await screen.findByRole("button", { name: "marlo" }));
    await user.click(await screen.findByRole("button", { name: /Write the descriptions/ }));
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Teach it" }) as HTMLButtonElement).disabled).toBe(
        false,
      ),
    );
    await user.click(screen.getByRole("button", { name: "Teach it" }));
    await user.click(await screen.findByRole("button", { name: /Cancel|Stop/ }));
    expect(await screen.findByText("Stopped")).toBeTruthy();
    expect(screen.getByText("Stopped.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Back to the pictures" }));
    expect(await screen.findByRole("navigation", { name: "Steps" })).toBeTruthy();
  });

  it("lists the models taught, renames one, and removes one after asking", async () => {
    const user = userEvent.setup();
    const engine = fake();
    engine.seed([
      {
        id: "m".repeat(32),
        run_id: "r",
        dataset_id: null,
        name: "Marlo",
        trigger_word: "marlo",
        kind: "character",
        base: "b",
        preview: true,
        adapter_bytes: 4,
        created_at: "",
        card: {
          base_title: "FLUX.2 klein base 4B",
          licence: "Apache-2.0",
          engine: "preview",
          preview: true,
          note: "",
          dataset: { name: "Marlo", kind: "character", pictures: 12, hash: "x" },
          steps: 200,
          seconds: 5,
          trigger_word: "marlo",
          statement: "x",
          evaluation: { passed: null, note: "" },
          trained_at: "",
        },
      },
    ]);
    render(<Train api={engine.api} pollMs={10} />);
    const section = await screen.findByRole("region", { name: "My models" });
    expect(within(section).getByText("Marlo")).toBeTruthy();
    expect(within(section).getByText("marlo", { selector: "code" })).toBeTruthy();
    expect(within(section).getByText("Preview")).toBeTruthy();
    await user.click(within(section).getByRole("button", { name: "Rename Marlo" }));
    const box = within(section).getByLabelText("Name");
    await user.clear(box);
    await user.type(box, "Marlo the fox");
    await user.click(within(section).getByRole("button", { name: "Save" }));
    expect(await within(section).findByText("Marlo the fox")).toBeTruthy();
    await user.click(within(section).getByRole("button", { name: "Remove Marlo the fox" }));
    expect(within(section).getByText("Marlo the fox")).toBeTruthy(); // asked first, not removed yet
    await user.click(within(section).getByRole("button", { name: /Yes, remove/ }));
    await waitFor(() => expect(screen.getByText("Nothing taught yet.")).toBeTruthy());
  });

  it("says where it is learnt: on this computer, or on the service", async () => {
    const { api } = fake();
    const { unmount } = render(<Train api={api} pollMs={10} />);
    expect(
      await screen.findByText(
        /learnt on this computer; your pictures and examples are not sent anywhere/,
      ),
    ).toBeTruthy();
    unmount();
    render(<Train api={api} place="service" pollMs={10} />);
    expect(await screen.findByText(/learnt on the service's graphics card/)).toBeTruthy();
    vi.restoreAllMocks();
  });

  it("shows what could stop a run or is worth knowing, before it starts", async () => {
    const user = userEvent.setup();
    const engine = fake({
      preflight: {
        ok: false,
        blockers: ["The battery is low (12%). Plug in before you start."],
        warnings: ["It is tight on memory. Close other apps first."],
        pauses: "Chat, images, video and 3D wait while it runs.",
      },
    });
    render(<Train api={engine.api} pollMs={10} />);
    await user.click(await screen.findByRole("button", { name: "Start" }));
    await user.upload(await screen.findByLabelText("Choose pictures"), [
      file("a.png"),
      file("b.png"),
      file("c.png"),
    ]);
    await user.click(await screen.findByRole("button", { name: "Next" }));
    await user.click(await screen.findByLabelText("It's a drawing, a character or an animal"));
    await user.click(await screen.findByRole("button", { name: "marlo" }));
    await user.click(await screen.findByRole("button", { name: /Write the descriptions \(3\)/ }));
    await waitFor(() =>
      expect(screen.getAllByDisplayValue("Standing on a beach.")).toHaveLength(3),
    );
    expect(await screen.findByText(/The battery is low \(12%\)/)).toBeTruthy();
    expect(screen.getByText(/It is tight on memory/)).toBeTruthy();
    expect(screen.getByText(/Chat, images, video and 3D wait/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Teach it" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("pauses a run that is going and carries on from where it stopped", async () => {
    const user = userEvent.setup();
    const engine = fake({ preview: false });
    render(<Train api={engine.api} pollMs={10} />);
    await user.click(await screen.findByRole("button", { name: "Start" }));
    await user.upload(await screen.findByLabelText("Choose pictures"), [
      file("a.png"),
      file("b.png"),
      file("c.png"),
    ]);
    await user.click(await screen.findByRole("button", { name: "Next" }));
    await user.click(await screen.findByLabelText("It's a drawing, a character or an animal"));
    await user.click(await screen.findByRole("button", { name: "marlo" }));
    await user.click(await screen.findByRole("button", { name: /Write the descriptions \(3\)/ }));
    await waitFor(() =>
      expect(screen.getAllByDisplayValue("Standing on a beach.")).toHaveLength(3),
    );
    await user.click(await screen.findByRole("button", { name: "Teach it" }));
    await user.click(await screen.findByRole("button", { name: "Pause" }));
    expect(await screen.findByRole("heading", { name: "Paused" })).toBeTruthy();
    expect(screen.getByText(/Paused at step 10 of 200/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Carry on" }));
    expect(await screen.findByText("Step 10 of 200")).toBeTruthy();
    expect(engine.log).toContain("resume");
  });

  it("finds a run the app left paused and offers to carry on or discard it", async () => {
    const user = userEvent.setup();
    const engine = fake();
    engine.leavePaused();
    render(<Train api={engine.api} pollMs={10} />);
    expect(await screen.findByText("Paused at step 75 of 200")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Carry on" }));
    await waitFor(() => expect(engine.log).toContain("resume"));
  });
});
