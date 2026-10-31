// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CreativeApi, CreativeProject } from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatScreenProps } from "../chat/ChatScreen";
import { Creative } from "./Creative";

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
    ...over,
  };
}

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
    await user.click(within(tabs).getByRole("tab", { name: "Titles" }));
    expect(screen.getByText(/Titles over the cut come with the Cut step/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Motion graphics" }));
    expect(onOpenScreen).toHaveBeenCalledWith("titles");
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

  it("keeps the step buttons for later stages switched off", async () => {
    render(<Creative api={api()} songs={songs} open="p1" />);
    expect(await screen.findByRole("radio", { name: "Shots" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Cut" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Make the stills" })).toBeDisabled();
  });
});
