// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CreativeApi, CreativeProject, CutState } from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatScreenProps } from "../chat/ChatScreen";
import { Creative } from "./Creative";
import { draftPieces, lanesOf } from "./CutStage";

// the chat has its own tests: here, what the screen gives it and does with what it reports
let chat: ChatScreenProps;
vi.mock("../chat/ChatScreen", () => ({
  ChatScreen: (props: ChatScreenProps) => {
    chat = props;
    return <div>The chat</div>;
  },
}));

const assistant = { runs: {}, api: {}, images: {} } as never;
const picture = {
  id: "pic-1",
  prompt: "A red barn",
  created_at: "2026-10-31T10:00:00Z",
  thumb_url: "/pic.png",
};
const noOthers = {
  models3d: [],
  compositions: [],
  creativeProjects: [],
  notebooks: [],
  taught: [],
};
const cardsOf = (images: unknown[]) =>
  ({
    images: { images },
    videos: null,
    songs: [
      { id: "t1", title: "Drive", created_at: "2026-10-01T10:00:00Z", seconds: 90, status: "done" },
    ],
    speeches: [],
    transcripts: [],
    lipsyncs: [],
    others: noOthers,
  }) as never;

const shot = (i: number, over = {}) => ({
  id: `s${i}`,
  start: i * 2,
  end: i * 2 + 2,
  beat: 0,
  shows: `Mira does thing ${i}`,
  who: ["Mira"],
  place: "a coast road",
  camera: "wide",
  line: "",
  note: "",
  motion: "Hold" as const,
  fallback: false,
  ...over,
}); // fmt: skip

function project(over: Partial<CreativeProject> = {}): CreativeProject {
  return {
    id: "p1",
    title: "Dawn drive",
    status: "planned",
    brief: {
      track_id: "t1",
      idea: "A drive at dawn",
      style: "",
      cast: [],
      places: [],
      lyrics: null,
      shape: "landscape",
      cut_speed: 0,
    }, // fmt: skip
    facts: { seconds: 6, bpm: 100, sections: [{ start: 0, end: 6, energy: 1, label: "mid" }] },
    plan: {
      places: ["a coast road"],
      beats: [{ what: "She sets out", who: "Mira", place: "a coast road" }],
      shots: [shot(0), shot(1, { fallback: true }), shot(2)],
    },
    revision: 1,
    stage: "",
    progress: 1,
    error: null,
    elapsed_s: 30,
    created_at: "",
    updated_at: "",
    live: false,
    shots: { takes: {}, missing: ["s0", "s1", "s2"], out_of_date: [], run: null, preview: null },
    shots_live: false,
    ...over,
  };
}

const take = (id: string, item: string, over = {}) => ({
  id,
  kind: "image" as const,
  item_id: item,
  mode: "reference",
  seconds: 30,
  prompt: "",
  created_at: "",
  out_of_date: false,
  chosen: true,
  ...over,
});
const ESTIMATE = {
  count: 3,
  portraits: 1,
  motions: { Hold: 3, Animate: 0, Sing: 0 },
  missing: 3,
  out_of_date: 0,
  seconds_low: 102,
  seconds_high: 126,
  bytes: 10 * 1024 ** 3,
  free_bytes: 100 * 1024 ** 3,
  fit: "fits" as const,
  measured: false,
  ready: true,
  step: null,
};

const MOTION = {
  quality: "draft" as const,
  count: 2,
  shots: 3,
  no_still: 1,
  start: 0,
  end: 6,
  loudest: true,
  sections: [{ start: 0, end: 6, label: "mid" }],
  seconds_low: 60,
  seconds_high: 120,
  bytes: 4 * 1024 ** 2,
  free_bytes: 100 * 1024 ** 3,
  fit: "fits" as const,
  measured: false,
  ready: true,
  step: null,
};

function api(over: Partial<CreativeApi> = {}): CreativeApi {
  return {
    analysis: vi.fn(async () => ({ state: "ready" as const })),
    installAnalysis: vi.fn(async () => {}),
    cancelAnalysis: vi.fn(async () => {}),
    list: vi.fn(async () => [project()]),
    byIds: vi.fn(async () => []),
    get: vi.fn(async () => project()),
    add: vi.fn(async () => project({ status: "draft", plan: null })),
    change: vi.fn(async () => project()),
    remove: vi.fn(async () => {}),
    plan: vi.fn(async () => project()),
    stop: vi.fn(async () => project({ status: "stopped", plan: null })),
    edit: vi.fn(async () => project({ revision: 2 })),
    undo: vi.fn(async () => project()),
    rewritePart: vi.fn(async () => project()),
    log: vi.fn(async () => []),
    keepConversation: vi.fn(async () => {}),
    media: vi.fn(async () => []),
    addMedia: vi.fn(async () => []),
    removeMedia: vi.fn(async () => []),
    characters: vi.fn(async () => []),
    estimateStills: vi.fn(async () => ESTIMATE),
    makeStills: vi.fn(async () => project()),
    stopStills: vi.fn(async () => project()),
    redoShot: vi.fn(async () => project()),
    chooseTake: vi.fn(async () => project()),
    estimateMotion: vi.fn(async () => MOTION),
    makeMotion: vi.fn(async () => project()),
    preview: vi.fn(async () => project()),
    editCut: vi.fn(async () => project({ cut: cutOf() })),
    undoCut: vi.fn(async () => project({ cut: cutOf() })),
    redoCut: vi.fn(async () => project({ cut: cutOf() })),
    makeVideo: vi.fn(async () => project({ cut: cutOf() })),
    keepVideo: vi.fn(async () => project({ cut: cutOf() })),
    ...over,
  };
}

const piece = (n: number, over = {}) => ({
  id: `c${n + 1}`,
  shot_id: `s${n}`,
  number: n + 1,
  start: n * 2,
  end: n * 2 + 2,
  length: 2,
  fade: false,
  source: null,
  kind: "image" as const,
  item_id: `pic-${n}`,
  camera: "wide",
  ...over,
});

function cutOf(over: Partial<CutState> = {}): CutState {
  return {
    items: [piece(0), piece(1, { fade: true }), piece(2, { kind: null, item_id: null })],
    captions: [
      { id: "t1", kind: "line", text: "Morning on the road", start: 0.5, end: 2.5 },
      { id: "t2", kind: "title", text: "Dawn drive", start: 4, end: 6 },
    ],
    captions_on: true,
    can_undo: true,
    can_redo: false,
    summary: {
      pictures_end: 6,
      song_s: 6,
      black_tail: 0,
      cut_short: 0,
      plan_changed: false,
      empty: 1,
    },
    render: null,
    exports: [],
    ...over,
  };
}

const songs = async () => [{ id: "t1", title: "Drive", seconds: 90, lyrics: "", url: "/song.wav" }];

afterEach(() => vi.restoreAllMocks());

describe("Creative Studio", () => {
  it("lists projects with where each one is", async () => {
    render(<Creative api={api()} songs={songs} />);
    expect(await screen.findByText("Dawn drive")).toBeInTheDocument();
    expect(screen.getByText(/Planned · 3 shots/)).toBeInTheDocument();
  });

  it("shows the size of the analysis tool before it downloads, and asks for no plan until it is there", async () => {
    const a = api({
      analysis: vi.fn(async () => ({ state: "missing" as const, bytes: 900_000_000 })),
    });
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} />);
    await user.click(await screen.findByRole("button", { name: "New project" }));
    const button = await screen.findByRole("button", { name: /Download and set up \(900 MB\)/ });
    expect(screen.getByRole("button", { name: "Plan it" })).toBeDisabled();
    await user.click(button);
    expect(a.installAnalysis).toHaveBeenCalledWith(900_000_000);
  });

  it("saves a changed shot when the person leaves it, and marks plain words", async () => {
    const a = api();
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    const box = await screen.findByRole("textbox", { name: "What shot 1 shows" });
    expect(screen.getByText("Plain words")).toBeInTheDocument();
    await user.clear(box);
    await user.type(box, "Mira starts the grey car");
    await user.tab();
    await waitFor(() =>
      expect(a.edit).toHaveBeenCalledWith("p1", [
        { op: "set_shot", shot_id: "s0", shows: "Mira starts the grey car" },
      ]),
    );
  });

  it("moves a cut by a beat, and the last shot has no cut to move", async () => {
    const a = api();
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("button", { name: "End shot 1 one beat later" }));
    expect(a.edit).toHaveBeenCalledWith("p1", [{ op: "move_cut", shot_id: "s0", by_beats: 1 }]);
    expect(screen.queryByRole("button", { name: "End shot 3 one beat later" })).toBeNull();
  });

  it("says why an edit was refused and keeps the plan", async () => {
    const a = api({
      edit: vi.fn(async () => Promise.reject(new Error("A shot holds, animates or sings."))),
    });
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("button", { name: "End shot 1 one beat later" }));
    expect(await screen.findByText("A shot holds, animates or sings.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "What shot 1 shows" })).toBeInTheDocument();
  });

  it("offers to go on after a crash, spending nothing until asked", async () => {
    const a = api({ get: vi.fn(async () => project({ status: "interrupted", plan: null })) });
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    const notice = await screen.findByText("The plan stopped when the app closed");
    expect(a.plan).not.toHaveBeenCalled();
    expect(notice).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Go on" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Go on" }));
    expect(a.plan).toHaveBeenCalledWith("p1", false);
  });

  it("shows progress and a stop while planning", async () => {
    const a = api({
      get: vi.fn(async () =>
        project({
          status: "planning",
          plan: null,
          live: true,
          stage: "Writing part 2",
          progress: 0.5,
        }),
      ),
    });
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    const card = await screen.findByRole("region", { name: "Progress" });
    expect(within(card).getByText("Writing part 2")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: /stop|cancel/i }));
    expect(a.stop).toHaveBeenCalledWith("p1");
  });

  it("has every product as a tab, moves between them with the arrow keys, and is honest about the ones to come", async () => {
    const user = userEvent.setup();
    const onOpenScreen = vi.fn();
    render(
      <Creative
        api={api()}
        songs={songs}
        open="p1"
        assistant={assistant}
        onOpenScreen={onOpenScreen}
      />,
    );
    const tabs = await screen.findByRole("tablist", { name: "Make something for this project" });
    expect(
      within(tabs)
        .getAllByRole("tab")
        .map((t) => t.textContent),
    ).toEqual(["Image", "Video", "Voice", "Music", "Titles", "3D", "Add", "Ask"]); // fmt: skip
    expect(within(tabs).getByRole("tab", { name: "Ask" })).toHaveAttribute("aria-selected", "true");
    within(tabs).getByRole("tab", { name: "Ask" }).focus();
    await user.keyboard("{ArrowLeft}");
    expect(within(tabs).getByRole("tab", { name: "Add" })).toHaveAttribute("aria-selected", "true");
    await user.click(within(tabs).getByRole("tab", { name: "3D" }));
    expect(screen.getByText(/3D comes after the Cut step/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open 3D models" }));
    expect(onOpenScreen).toHaveBeenCalledWith("model3d");
  });

  it("keeps the chat while another tab shows, and tells it the project and the selected shot", async () => {
    const user = userEvent.setup();
    render(<Creative api={api()} songs={songs} open="p1" assistant={assistant} />);
    await screen.findByText("The chat");
    expect(chat.runInput).toEqual({
      working_on: {
        action_id: "creative.read_project",
        params: { project_id: "p1", shot_id: undefined },
      },
    });
    await user.click(screen.getByRole("button", { name: "Shot 2" }));
    expect(screen.getByRole("button", { name: "Shot 2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Working on shot 2.")).toBeInTheDocument();
    expect((chat.runInput?.working_on as { params: object }).params).toEqual({
      project_id: "p1",
      shot_id: "s1",
    });
    await user.click(screen.getByRole("tab", { name: "Image" }));
    expect(screen.getByText("The chat")).not.toBeVisible();
    expect(chat).toBeTruthy();
  });

  it("shows the assistant's change at once and its card takes back that change and later ones", async () => {
    const a = api();
    const said = (id: string) =>
      ({ id, status: "ok", output: { action_id: "creative.edit_plan" } }) as never;
    render(<Creative api={a} songs={songs} open="p1" assistant={assistant} />);
    await screen.findByText("The chat");
    expect(chat.undoOfTool?.("from-an-earlier-visit")).toBeNull();
    vi.mocked(a.get).mockResolvedValue(project({ revision: 2 }));
    await act(async () => chat.onToolResult?.(said("t1")));
    vi.mocked(a.get).mockResolvedValue(project({ revision: 3 }));
    await act(async () => chat.onToolResult?.(said("t2")));
    expect(await screen.findByText("Plan 3 · saved")).toBeInTheDocument();
    expect(chat.undoOfTool?.("t1")?.undone).toBe(false);
    vi.mocked(a.undo)
      .mockResolvedValueOnce(project({ revision: 2 }))
      .mockResolvedValueOnce(project({ revision: 1 }));
    await act(async () => chat.undoOfTool?.("t1")?.undo());
    expect(await screen.findByText("Plan 1 · saved")).toBeInTheDocument();
    expect(a.undo).toHaveBeenCalledTimes(2);
    expect(chat.undoOfTool?.("t1")?.undone).toBe(true);
    expect(chat.undoOfTool?.("t2")?.undone).toBe(true);
    // a change that was refused is not one to undo or reload
    vi.mocked(a.get).mockClear();
    await act(async () =>
      chat.onToolResult?.({
        id: "t2",
        status: "refused",
        output: { action_id: "creative.edit_plan" },
      } as never),
    );
    expect(a.get).not.toHaveBeenCalled();
  });

  it("adds from the library to the rail for the selected shot, and takes it out again", async () => {
    const tag = { kind: "image", item_id: "pic-1", shot_id: "s0", created_at: "" };
    const a = api({
      addMedia: vi.fn(async () => [tag]),
      removeMedia: vi.fn(async () => []),
    });
    const creations = {
      recent: vi.fn(async () => cardsOf([picture])),
      cards: vi.fn(async (ids: { image?: string[] }) => cardsOf(ids.image ? [picture] : [])),
    };
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" creations={creations} />);
    const rail = await screen.findByRole("complementary", { name: "Media of this project" });
    // the song is always there and cannot be taken out
    expect(await within(rail).findByText("Drive")).toBeInTheDocument();
    expect(within(rail).queryByRole("button")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Shot 1" }));
    await user.click(await screen.findByRole("button", { name: "Add: A red barn" }));
    expect(a.addMedia).toHaveBeenCalledWith("p1", "image", "pic-1", "s0");
    expect(await within(rail).findByText("A red barn")).toBeInTheDocument();
    expect(within(rail).getByText("Shot 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Already added: A red barn" })).toBeDisabled();
    await user.click(
      within(rail).getByRole("button", { name: "Take out of this project: A red barn" }),
    );
    expect(a.removeMedia).toHaveBeenCalledWith("p1", "image", "pic-1");
    await waitFor(() => expect(within(rail).queryByText("A red barn")).toBeNull());
  });

  it("says why a thing could not be added, and shows the planning log when asked", async () => {
    const a = api({
      addMedia: vi.fn(async () => {
        throw new Error("That is not in the library.");
      }),
      log: vi.fn(async () => [
        { step: "shots", asked: "Write the shots", said: "Done", created_at: "" },
      ]),
    });
    const creations = {
      recent: vi.fn(async () => cardsOf([picture])),
      cards: vi.fn(async () => cardsOf([])),
    };
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" creations={creations} />);
    await user.click(await screen.findByRole("button", { name: "Add: A red barn" }));
    expect(await screen.findByText("That is not in the library.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Planning log" }));
    expect(await screen.findByText("Write the shots")).toBeInTheDocument();
  });

  it("keeps the Cut step off until there is a plan and goes to the Shots step with its button", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <Creative
        api={api({ get: vi.fn(async () => project({ revision: 0, plan: null, status: "draft" })) })}
        songs={songs}
        open="p1"
      />,
    );
    expect(await screen.findByRole("radio", { name: "Cut" })).toBeDisabled();
    unmount();
    render(<Creative api={api()} songs={songs} open="p1" />);
    expect(await screen.findByRole("radio", { name: "Cut" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Make the stills" }));
    expect(await screen.findByText("3 stills to make")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview the whole song" })).toBeDisabled();
  });

  it("says what the stills will take before they start, and starts from reference pictures", async () => {
    const a = api();
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("radio", { name: "Shots" }));
    expect(await screen.findByText(/About 2 minutes to 2 minutes/)).toBeInTheDocument();
    expect(screen.getByText(/1 person gets two pictures first/)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Plain, about twice as fast" }));
    await waitFor(() => expect(a.estimateStills).toHaveBeenCalledWith("p1", "plain", false));
    await user.click(screen.getByRole("radio", { name: "From reference pictures" }));
    await user.click(screen.getByRole("button", { name: "Start" }));
    expect(a.makeStills).toHaveBeenCalledWith("p1", "reference", false);
  });

  it("will not start when the picture model is missing or the disk is too small, and says why", async () => {
    const a = api({
      estimateStills: vi.fn(async () => ({
        ...ESTIMATE,
        ready: false,
        step: "Choose a picture model first.",
        fit: "too_big" as const,
      })),
    });
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("radio", { name: "Shots" }));
    expect(await screen.findByText("Choose a picture model first.")).toBeInTheDocument();
    expect(screen.getByText("There is not enough room on the disk")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("shows the run with its Stop, and what a stop keeps", async () => {
    const run = {
      kind: "stills" as const,
      status: "running" as const,
      stage: "Making the still of shot 2",
      finished: 1,
      total: 3,
      failed: 0,
      error: null,
    };
    const shots = { takes: {}, missing: ["s1", "s2"], out_of_date: [], preview: null };
    const a = api({
      get: vi.fn(async () => project({ shots_live: true, shots: { ...shots, run } })),
      stopStills: vi.fn(async () =>
        project({ shots: { ...shots, run: { ...run, status: "stopped" as const } } }),
      ),
    });
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("radio", { name: "Shots" }));
    expect(await screen.findByText("1 of 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Stop|Cancel/ }));
    expect(a.stopStills).toHaveBeenCalledWith("p1");
    expect(await screen.findByText(/going on makes only what is missing/)).toBeInTheDocument();
  });

  it("shows the stills with their takes, chooses a take with a click, marks what is out of date, and previews", async () => {
    const shots = {
      takes: {
        s0: [take("a", "pic-1", { chosen: false }), take("b", "pic-2", { out_of_date: true })],
        s1: [take("c", "pic-1")],
        s2: [],
      },
      missing: ["s2"],
      out_of_date: ["s0"],
      run: null,
      preview: {
        url: "/preview.mp4",
        seconds: 6,
        empty_shots: 1,
        took_s: 3,
        created_at: "",
        current: false,
      },
    };
    const a = api({
      get: vi.fn(async () => project({ shots })),
      chooseTake: vi.fn(async () => project({ shots })),
      redoShot: vi.fn(async () => project({ shots })),
      preview: vi.fn(async () => project({ shots })),
      media: vi.fn(async () => [
        { kind: "image", item_id: "pic-1", shot_id: "s0", created_at: "" },
      ]),
    });
    const creations = {
      recent: vi.fn(async () => cardsOf([])),
      cards: vi.fn(async () => cardsOf([picture])),
    };
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" creations={creations} />);
    await user.click(await screen.findByRole("radio", { name: "Shots" }));
    expect(await screen.findByText(/1 shot is black, having no still/)).toBeInTheDocument();
    expect(screen.getByText(/The shots have changed since/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Shot 1, out of date" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Shot 3, no still yet" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Version 1 of shot 1" }));
    expect(a.chooseTake).toHaveBeenCalledWith("p1", "s0", "a");
    await user.click(screen.getByRole("button", { name: "Make it again" }));
    expect(a.redoShot).toHaveBeenCalledWith("p1", "s0", "reference");
    await user.click(screen.getByRole("button", { name: "Preview the whole song" }));
    expect(a.preview).toHaveBeenCalledWith("p1");
  });

  it("says what a draft of the motion will take, starts it where asked, and makes it better or one shot's clip", async () => {
    const shots = {
      takes: { s0: [take("a", "pic-1")], s1: [take("b", "pic-2")], s2: [] },
      missing: ["s2"],
      out_of_date: [],
      run: null,
      preview: null,
    };
    const a = api({
      get: vi.fn(async () => project({ shots })),
      makeMotion: vi.fn(async () => project({ shots })),
    });
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("radio", { name: "Shots" }));
    const motion = await screen.findByRole("region", { name: "Motion" });
    expect(
      await within(motion).findByText(/marked Animate or Sing in the plan\. 2 clips to make/),
    ).toBeInTheDocument();
    expect(within(motion).getByText("Some shots have no still")).toBeInTheDocument();
    // sharp clips by default; the draft is a soft preview the person picks
    expect(a.estimateMotion).toHaveBeenCalledWith("p1", { quality: "final", start: undefined });
    await user.click(within(motion).getByRole("button", { name: "Make it better" }));
    expect(a.makeMotion).toHaveBeenCalledWith("p1", { quality: "final", start: undefined });
    await user.click(screen.getByRole("button", { name: "Shot 1" }));
    await user.click(screen.getByRole("button", { name: "Make a clip" }));
    expect(a.makeMotion).toHaveBeenCalledWith("p1", { quality: "final", shot_id: "s0" });
    await user.click(within(motion).getByRole("radio", { name: "Draft 30 seconds" }));
    expect(
      await within(motion).findByText(
        /0:00 to 0:06: 3 shots\. 2 clips to make, about 60 seconds to 2 minutes/,
      ),
    ).toBeInTheDocument();
    expect(a.estimateMotion).toHaveBeenCalledWith("p1", { quality: "draft", start: undefined });
    await user.click(within(motion).getByRole("button", { name: "Draft 30 seconds" }));
    expect(a.makeMotion).toHaveBeenCalledWith("p1", { quality: "draft", start: undefined });
    expect(screen.getByRole("button", { name: "Make a draft clip" })).toBeInTheDocument();
  });

  it("will not animate without the video model, and shows clips and the time left while they are made", async () => {
    const blocked = api({
      get: vi.fn(async () =>
        project({
          shots: {
            takes: { s0: [take("a", "pic-1")] },
            missing: ["s1", "s2"],
            out_of_date: [],
            run: null,
            preview: null,
          },
        }),
      ),
      estimateMotion: vi.fn(async () => ({
        ...MOTION,
        ready: false,
        step: "Get the video model first.",
      })),
    }); // fmt: skip
    const user = userEvent.setup();
    const { unmount } = render(<Creative api={blocked} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("radio", { name: "Shots" }));
    expect(await screen.findByText("Get the video model first.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make it better" })).toBeDisabled();
    unmount();

    const clip = take("c", "vid-1", {
      kind: "video" as const,
      mode: "draft",
      seconds: 50,
      created_at: "2",
    });
    const run = {
      kind: "motion" as const,
      status: "running" as const,
      stage: "Animating shot 2",
      finished: 1,
      total: 3,
      failed: 0,
      error: null,
    };
    const live = api({
      get: vi.fn(async () =>
        project({
          shots_live: true,
          shots: {
            takes: { s0: [take("a", "pic-1", { chosen: false }), clip] },
            missing: ["s1", "s2"],
            out_of_date: [],
            run,
            preview: null,
          },
        }),
      ),
    }); // fmt: skip
    render(<Creative api={live} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("radio", { name: "Shots" }));
    expect(await screen.findByText("1 of 3")).toBeInTheDocument();
    expect(screen.getByText("Animating shot 2")).toBeInTheDocument();
    expect(screen.getByText(/About 100 seconds left|About 2 minutes left/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Shot 1, draft clip" })).toBeInTheDocument();
  });

  it("gives what a make tab makes to the selected shot, and adds a dropped file", async () => {
    const a = api({ addMedia: vi.fn(async () => []) });
    const addFile = vi.fn(async () => ({ kind: "image", id: "new-file" }));
    const pictureModel = <span>Picture model</span>;
    const makers = {
      image: (onMade: (id: string) => void) => (
        <button type="button" onClick={() => onMade("made-1")}>
          Pretend it was made
        </button>
      ),
    };
    const user = userEvent.setup();
    render(
      <Creative
        api={a}
        songs={songs}
        open="p1"
        makers={makers}
        addFile={addFile}
        modelOfTab={(tab) => (tab === "image" ? pictureModel : undefined)}
        model={<span>Chat model</span>}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "Make the stills" }));
    expect(await screen.findByText("Picture model")).toBeInTheDocument();
    expect(screen.getByText(/What you make here is a version of shot 1/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pretend it was made" }));
    expect(a.addMedia).toHaveBeenCalledWith("p1", "image", "made-1", "s0");
    await user.click(screen.getByRole("tab", { name: "Add" }));
    await user.upload(
      screen.getByLabelText("Choose a picture, clip or sound to add"),
      new File(["x"], "mine.png", { type: "image/png" }),
    );
    await waitFor(() => expect(addFile).toHaveBeenCalled());
    await waitFor(() => expect(a.addMedia).toHaveBeenCalledWith("p1", "image", "new-file", "s0"));
  });

  it("plans a story read by saved voices with no song and no music analysis", async () => {
    const a = api({
      list: vi.fn(async () => []),
      analysis: vi.fn(async () => ({ state: "missing" as const, bytes: 900_000_000 })),
    });
    const voices = async () => [
      { id: "v-n", name: "Narrator" },
      { id: "v-m", name: "Mira's voice" },
    ];
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} voices={voices} />);
    await user.click(await screen.findByRole("button", { name: "New project" }));
    await user.click(await screen.findByRole("radio", { name: "A story" }));
    expect(screen.queryByRole("button", { name: /Download and set up/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("The song's words")).not.toBeInTheDocument();
    const plan = screen.getByRole("button", { name: "Plan it" });
    await user.type(screen.getByLabelText("What is the video about?"), "Opening the old house");
    await user.type(screen.getByLabelText("The story"), "Too short.");
    expect(plan).toBeDisabled();
    await user.type(
      screen.getByLabelText("The story"),
      ' Mira found the key. "It fits," said Mira.',
    );
    await user.click(screen.getByLabelText("Who reads it"));
    await user.click(await screen.findByRole("option", { name: "Narrator" }));
    await user.click(screen.getByRole("button", { name: "Add a person" }));
    await user.type(screen.getByLabelText("Name of person 1"), "Mira");
    await user.click(screen.getByLabelText("Voice of Mira"));
    await user.click(await screen.findByRole("option", { name: "Mira's voice" }));
    expect(plan).toBeEnabled();
    await user.click(plan);
    const [, brief] = (a.add as ReturnType<typeof vi.fn>).mock.calls[0] as [string, never];
    expect(brief).toMatchObject({
      skill: "story",
      track_id: "",
      narrator: "v-n",
      lyrics: null,
      story: 'Too short. Mira found the key. "It fits," said Mira.',
      cast: [{ name: "Mira", voice: "v-m" }],
    });
  });

  it("makes a Sing shot sing, and shows its sung clip with the still it came from", async () => {
    const sung = { ...take("c", "clip-1", { kind: "lipsync", mode: "sing" }) };
    const shots = {
      takes: { s0: [take("a", "pic-1", { chosen: false }), sung], s1: [], s2: [] },
      missing: ["s1", "s2"],
      out_of_date: [],
      run: null,
      preview: null,
    };
    const plan = {
      places: ["a coast road"],
      beats: [{ what: "She sings", who: "Mira", place: "a coast road" }],
      shots: [shot(0, { motion: "Sing", line: "Take me home" }), shot(1), shot(2)],
    };
    const a = api({
      get: vi.fn(async () => project({ shots, plan })),
      estimateMotion: vi.fn(async () => ({ ...MOTION, quality: "final" as const, sung: 1 })),
    });
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("radio", { name: "Shots" }));
    expect(await screen.findByRole("button", { name: "Shot 1, sung clip" })).toBeInTheDocument();
    const motion = screen.getByRole("region", { name: "Motion" });
    expect(await within(motion).findByText(/2 clips to make \(1 sings\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Shot 1, sung clip" }));
    await user.click(screen.getByRole("button", { name: "Make it sing" }));
    expect(a.makeMotion).toHaveBeenCalledWith("p1", { quality: "final", shot_id: "s0" });
  });

  it("counts the pieces of the cut that show a draft clip", () => {
    const draft = take("d", "vid-0", { kind: "video" as const, mode: "draft" });
    const sharp = take("f", "vid-1", { kind: "video" as const, mode: "final" });
    const p = project({
      shots: {
        takes: { s0: [draft], s1: [sharp] },
        missing: [],
        out_of_date: [],
        run: null,
        preview: null,
      },
    });
    const items = [
      piece(0, { kind: "video", item_id: "vid-0" }),
      piece(1, { kind: "video", item_id: "vid-1" }),
      piece(2),
    ];
    expect(draftPieces(p, cutOf({ items }))).toBe(1);
    expect(draftPieces(p, cutOf())).toBe(0);
  });

  it("offers people used before and keeps fixed words for objects", async () => {
    const a = api({
      list: vi.fn(async () => []),
      characters: vi.fn(async () => [
        { name: "Mira", look: "short hair", photos_only: false, pictures: ["x"] },
      ]),
    });
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} />);
    await user.click(await screen.findByRole("button", { name: "New project" }));
    expect(await screen.findByLabelText("Someone you have used before")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add an object or place" }));
    expect(screen.getByLabelText("Name of thing 1")).toBeInTheDocument();
  });

  it("shows the cut on a timeline, changes the chosen piece and caption, and takes keys", async () => {
    const withTakes = {
      ...project().shots,
      takes: { s0: [take("a", "pic-0"), take("b", "pic-9", { chosen: false })] },
    };
    const a = api({ get: vi.fn(async () => project({ cut: cutOf(), shots: withTakes })) });
    a.editCut = vi.fn(async () => project({ cut: cutOf(), shots: withTakes }));
    a.chooseTake = vi.fn(async () => project({ cut: cutOf(), shots: withTakes }));
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("radio", { name: "Cut" }));
    expect(screen.getByText("No video of this cut yet")).toBeInTheDocument();
    expect(screen.getByText(/1 piece has no picture yet, so it is black/)).toBeInTheDocument();
    const pictures = screen.getByRole("list", { name: "Pictures" });
    expect(
      within(pictures)
        .getAllByRole("button")
        .map((b) => b.getAttribute("aria-label")),
    ).toEqual([
      "Piece 1: shot 1, 2 s from 0:00",
      "Piece 2: shot 2, 2 s from 0:02, fades in",
      "Piece 3: shot 3, 2 s from 0:04, no picture yet",
    ]); // fmt: skip
    await user.click(within(pictures).getAllByRole("button")[0]);
    await user.click(screen.getByRole("button", { name: "Longer" }));
    expect(a.editCut).toHaveBeenLastCalledWith("p1", [
      { op: "length", item_id: "c1", by_beats: 1 },
    ]);
    await user.click(screen.getByRole("button", { name: "Move later" }));
    expect(a.editCut).toHaveBeenLastCalledWith("p1", [{ op: "move", item_id: "c1", to: 1 }]);
    expect(screen.getByRole("button", { name: "Move earlier" })).toBeDisabled();
    await user.click(screen.getByRole("combobox", { name: "Version of shot 1" }));
    await user.click(await screen.findByRole("option", { name: "Version 2" }));
    expect(a.chooseTake).toHaveBeenCalledWith("p1", "s0", "b");
    within(pictures).getAllByRole("button")[0].focus();
    await user.keyboard("s");
    expect(a.editCut).toHaveBeenLastCalledWith("p1", [{ op: "split", item_id: "c1" }]);
    await user.keyboard("{ArrowLeft}");
    expect(a.editCut).toHaveBeenLastCalledWith("p1", [
      { op: "length", item_id: "c1", by_beats: -1 },
    ]);
    await user.keyboard("z");
    expect(a.undoCut).toHaveBeenCalledWith("p1");
    expect(screen.getByRole("button", { name: /Redo/ })).toBeDisabled();
    expect(
      within(screen.getByRole("list", { name: "Captions" })).getAllByRole("button"),
    ).toHaveLength(1);
    const titles = screen.getByRole("list", { name: "Titles" });
    await user.click(within(titles).getByRole("button", { name: "Title at 0:04: Dawn drive" }));
    const words = screen.getByRole("textbox", { name: "Its words" });
    await user.clear(words);
    await user.type(words, "Dawn drive home{Enter}");
    expect(a.editCut).toHaveBeenLastCalledWith("p1", [
      { op: "caption", caption_id: "t2", text: "Dawn drive home" },
    ]);
    await user.click(screen.getByRole("button", { name: "A beat later" }));
    expect(a.editCut).toHaveBeenLastCalledWith("p1", [
      { op: "caption", caption_id: "t2", by_beats: 1 },
    ]);
  });

  it("makes the video, says when the cut changed since, keeps it and saves a copy", async () => {
    const made = {
      url: "/cut.mp4",
      shape: "landscape" as const,
      seconds: 6,
      bytes: 9,
      took_s: 4,
      created_at: "",
      current: false,
    }; // fmt: skip
    const kept = [{ video_id: "v1", title: "Dawn drive", created_at: "2026-11-02T10:00:00Z" }];
    const a = api({
      get: vi.fn(async () => project({ cut: cutOf({ render: made, exports: kept }) })),
      keepVideo: vi.fn(async () => project({ cut: cutOf({ render: made, exports: kept }) })),
      makeVideo: vi.fn(async () => project({ cut: cutOf({ render: made, exports: kept }) })),
    });
    const saveVideo = vi.fn(async () => ({
      name: "dawn-drive.mp4",
      path: "/Users/me/Downloads/dawn-drive.mp4",
    }));
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" saveVideo={saveVideo} />);
    await user.click(await screen.findByRole("radio", { name: "Cut" }));
    expect(screen.getByLabelText("The video of the cut")).toHaveAttribute("src", "/cut.mp4");
    expect(screen.getByText(/The cut has changed since/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Make it again to watch" }));
    expect(a.makeVideo).toHaveBeenCalledWith("p1");
    await user.click(screen.getByRole("button", { name: "Make the video" }));
    expect(a.keepVideo).toHaveBeenCalledWith("p1");
    expect(screen.getByText("Kept in Your videos")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save a copy" }));
    expect(saveVideo).toHaveBeenCalledWith("v1");
    expect(
      await screen.findByText("Saved to /Users/me/Downloads/dawn-drive.mp4."),
    ).toBeInTheDocument();
  });

  it("puts the song's words and titles in the Voice and Titles tabs, and says when the plan changed", async () => {
    const now = project({
      facts: { seconds: 6, lines_timed: true },
      cut: cutOf({ summary: { ...cutOf().summary, plan_changed: true, black_tail: 1.5 } }),
    });
    const a = api({ get: vi.fn(async () => now), editCut: vi.fn(async () => now) });
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" />);
    await user.click(await screen.findByRole("radio", { name: "Cut" }));
    expect(screen.getByText(/The pictures end 1.5 s before the song/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start again from the plan" }));
    expect(a.editCut).toHaveBeenLastCalledWith("p1", [{ op: "reset" }]);
    await user.click(screen.getByRole("tab", { name: "Voice" }));
    await user.click(screen.getByRole("checkbox", { name: "Show the song's words" }));
    expect(a.editCut).toHaveBeenLastCalledWith("p1", [{ op: "captions", on: false }]);
    await user.click(screen.getByRole("button", { name: "Take the words from the song again" }));
    expect(a.editCut).toHaveBeenLastCalledWith("p1", [{ op: "song_lines" }]);
    await user.click(screen.getByRole("tab", { name: "Titles" }));
    await user.click(screen.getByRole("radio", { name: "Lower third" }));
    await user.type(screen.getByLabelText("Words"), "Mira, on the road home");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(a.editCut).toHaveBeenLastCalledWith("p1", [
      { op: "add_caption", kind: "lower", text: "Mira, on the road home", start: 0, end: 3 },
    ]);
  });

  it("says a line in the Voice tab beside the captions, and a lip sync made in the Video tab is a take", async () => {
    const now = project({ facts: { seconds: 6, lines_timed: true }, cut: cutOf() });
    const a = api({ get: vi.fn(async () => now), addMedia: vi.fn(async () => []) });
    const makers = {
      voice: (onMade: (id: string, kind?: string) => void) => (
        <button type="button" onClick={() => onMade("speech-1", "speech")}>
          Pretend it was said
        </button>
      ),
      video: (onMade: (id: string, kind?: string) => void) => (
        <button type="button" onClick={() => onMade("clip-1", "lipsync")}>
          Pretend it sang
        </button>
      ),
    };
    const user = userEvent.setup();
    render(<Creative api={a} songs={songs} open="p1" makers={makers} />);
    await user.click(await screen.findByRole("radio", { name: "Cut" }));
    await user.click(screen.getByRole("tab", { name: "Voice" }));
    expect(screen.getByRole("checkbox", { name: "Show the song's words" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Speak" }));
    await user.click(screen.getByRole("button", { name: "Pretend it was said" }));
    await waitFor(() =>
      expect(a.addMedia).toHaveBeenCalledWith("p1", "speech", "speech-1", undefined),
    );
    await user.click(screen.getByRole("tab", { name: "Video" }));
    await user.click(screen.getByRole("button", { name: "Pretend it sang" }));
    await waitFor(() =>
      expect(a.addMedia).toHaveBeenLastCalledWith("p1", "lipsync", "clip-1", undefined),
    );
  });

  it("puts words that would touch on another line of their row", () => {
    const at = (start: number, end: number) => ({
      id: `${start}`,
      kind: "line" as const,
      text: "x",
      start,
      end,
    });
    // 90 s: the narrowest is 1.5 of 36rem, about 3.75 s
    expect(lanesOf([at(0, 10), at(10, 11), at(12, 20), at(13, 14), at(30, 40)], 90)).toEqual([
      0, 0, 1, 2, 0,
    ]);
  });
});
