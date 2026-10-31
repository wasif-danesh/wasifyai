// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { BuilderProject, SceneDocument, VideoBuilderApi } from "@wasifyai/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SceneEditor } from "./SceneEditor";
import { lengthOf, newSceneId, sceneAt, startOf, withWorkedOut } from "./use-scene-editor";

vi.mock("./vendor/hyperframes-player.global.js", () => ({}));

const THEME = { from: "#000", to: "#111", ink: "#fff", accent: "#f00" };
const seconds = {
  id: "seconds",
  kind: "seconds" as const,
  label: "Length",
  required: false,
  max_chars: 0,
  min: 3,
  max: 90,
  default: 30,
  choices: [],
  hint: "",
};
const catalogue = {
  templates: [
    {
      id: "title",
      title: "Animated title",
      description: "A title.",
      transparent: false,
      formats: ["mp4" as const],
      fields: [
        {
          ...seconds,
          id: "title",
          kind: "text" as const,
          label: "Title",
          required: true,
          max_chars: 80,
          min: 0,
          max: 0,
          default: null,
        },
        seconds,
      ],
    },
    {
      id: "quote",
      title: "Quote",
      description: "A quote.",
      transparent: false,
      formats: ["mp4" as const],
      fields: [
        {
          ...seconds,
          id: "quote",
          kind: "longtext" as const,
          label: "Quote",
          required: true,
          max_chars: 220,
          min: 0,
          max: 0,
          default: null,
        },
        { ...seconds, min: 4 },
      ],
    },
  ],
  shapes: {},
  themes: {
    midnight: THEME,
    sunrise: THEME,
    forest: THEME,
    paper: THEME,
    night: THEME,
    sage: THEME,
    pulse: THEME,
  },
  fonts: {},
} as never;

const film: SceneDocument = {
  name: "Launch", shape: "portrait", font: "sans", seconds: 12,
  scenes: [
    { id: "aaaaaaaa", name: "Hook", kind: "title", caption: "", transition: "fade", fields: { title: "First", seconds: 4, theme: "midnight" } },
    { id: "bbbbbbbb", name: "Proof", kind: "quote", caption: "", transition: "none", fields: { quote: "Second", seconds: 8, theme: "paper" } },
  ],
}; // biome-ignore format: the sample reads best in rows

const first = film.scenes[0] as SceneDocument["scenes"][number];

function project(slots: SceneDocument = film): BuilderProject {
  return {
    id: "p".repeat(32),
    title: "Launch",
    template: "scenes",
    slots: slots as never,
    created_at: "",
    updated_at: "",
    renders: [],
    formats: ["mp4"],
    preview_times: [],
    can_undo: false,
  };
}

function rig(over: Partial<VideoBuilderApi> = {}) {
  const update = vi.fn(async (_id: string, slots: unknown) => project(slots as SceneDocument));
  const api = {
    update,
    live: vi.fn(async () => ({
      url: "http://engine/live/t/index.html",
      expires_at: Date.now() / 1000 + 3600,
    })),
    undo: vi.fn(),
    render: vi.fn(async () => ({
      id: "r1",
      status: "working",
      progress: 0,
      stage: "checking",
      check: null,
      error: null,
      video_id: null,
      video_url: null,
      poster_url: null,
      format: "mp4",
    })),
    renderStatus: vi.fn(),
    cancel: vi.fn(),
    ...over,
  } as unknown as VideoBuilderApi;
  render(<SceneEditor api={api} project={project()} catalogue={catalogue} onBack={() => {}} />);
  return { api, update };
}

const saves = async (update: ReturnType<typeof vi.fn>) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(600);
  });
  return update.mock.calls.at(-1)?.[1] as SceneDocument;
};

describe("the sums the editor does", () => {
  it("knows when each scene starts and which one is playing", () => {
    expect(lengthOf(film)).toBe(12);
    expect(startOf(film, 1)).toBe(4);
    expect(sceneAt(film, 3.9)).toBe(0);
    expect(sceneAt(film, 4)).toBe(1);
    expect(sceneAt(film, 99)).toBe(1);
  });

  it("makes ids the engine keeps", () => {
    expect(newSceneId(film)).toMatch(/^[0-9a-f]{8}$/);
  });

  it("takes lengths from the engine, never the words being typed", () => {
    const local = {
      ...film,
      scenes: [{ ...first, name: "", fields: { title: "Typing ", seconds: 0 } }],
    };
    const saved = {
      ...film,
      scenes: [{ ...first, name: "Animated title", fields: { title: "Typing", seconds: 6 } }],
    };
    const merged = withWorkedOut(local, saved).scenes[0] as SceneDocument["scenes"][number];
    expect(merged.fields).toEqual({ title: "Typing ", seconds: 6 });
    expect(merged.name).toBe("Animated title");
  });
});

describe("the editor", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("opens the player on the address the engine gave", async () => {
    rig();
    await waitFor(() => {
      const player = document.querySelector("hyperframes-player");
      expect(player?.getAttribute("src")).toBe("http://engine/live/t/index.html?v=0");
    });
    expect(screen.getByText("Scene 1 of 2")).toBeTruthy();
  });

  it("selecting a scene shows its details", async () => {
    rig();
    fireEvent.click(screen.getByRole("button", { name: /Scene 2, Proof/ }));
    expect(screen.getByText("Scene 2 of 2")).toBeTruthy();
    expect((screen.getByLabelText(/Quote/) as HTMLTextAreaElement).value).toBe("Second");
  });

  it("saves a typing session once, and one Undo takes all of it back", async () => {
    const { update } = rig();
    const title = screen.getByLabelText(/^Title/);
    fireEvent.change(title, { target: { value: "Fi" } });
    fireEvent.change(title, { target: { value: "Fir" } });
    fireEvent.change(title, { target: { value: "Firm" } });
    expect(update).not.toHaveBeenCalled();
    const sent = await saves(update);
    expect(update).toHaveBeenCalledTimes(1);
    expect(sent.scenes[0]?.fields.title).toBe("Firm");
    await waitFor(() => expect(screen.getByText("Saved")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Undo: Change the words" }));
    expect((screen.getByLabelText(/^Title/) as HTMLInputElement).value).toBe("First");
    fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    expect((screen.getByLabelText(/^Title/) as HTMLInputElement).value).toBe("Firm");
  });

  it("reloads the player after a save, so it shows the new words", async () => {
    const { update } = rig();
    await waitFor(() => expect(document.querySelector("hyperframes-player")).toBeTruthy());
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "New" } });
    await saves(update);
    await waitFor(() =>
      expect(document.querySelector("hyperframes-player")?.getAttribute("src")).toContain("?v=1"),
    );
  });

  it("says plainly when a change is not saved, and keeps it", async () => {
    const update = vi.fn(async () => {
      throw new Error("Scene 1: Write a title.");
    });
    rig({ update } as never);
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    await waitFor(() => expect(screen.getByText("Not saved")).toBeTruthy());
    expect(screen.getByText("Scene 1: Write a title.")).toBeTruthy();
    expect((screen.getByLabelText(/^Title/) as HTMLInputElement).value).toBe("");
  });

  it("adds, copies, moves and removes scenes, and each is one Undo", async () => {
    const { update } = rig();
    fireEvent.click(screen.getByRole("button", { name: /^Quote/ }));
    expect(screen.getByText("Scene 2 of 3")).toBeTruthy();
    const added = await saves(update);
    expect(added.scenes.map((s) => s.kind)).toEqual(["title", "quote", "quote"]);
    expect(added.scenes[1]?.transition).toBe("fade");
    fireEvent.click(screen.getByRole("button", { name: "Duplicate" }));
    expect(screen.getByText("Scene 3 of 4")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByText("Scene 3 of 3")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Move this scene earlier" }));
    expect(screen.getByText("Scene 2 of 3")).toBeTruthy();
    const moved = await saves(update);
    expect(moved.scenes[1]?.id).toBe("bbbbbbbb");
    fireEvent.click(screen.getByRole("button", { name: "Undo: Move a scene" }));
    expect(screen.getByRole("button", { name: "Undo: Remove a scene" })).toBeTruthy();
  });

  it("will not remove the last scene", () => {
    const update = vi.fn();
    const api = {
      update,
      live: vi.fn(async () => ({ url: "x", expires_at: 0 })),
    } as unknown as VideoBuilderApi;
    render(
      <SceneEditor
        api={api}
        project={project({ ...film, scenes: [first] })}
        catalogue={catalogue}
        onBack={() => {}}
      />,
    );
    expect((screen.getByRole("button", { name: "Remove" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("changes the length within what the scene allows", async () => {
    const { update } = rig();
    fireEvent.click(screen.getByRole("button", { name: "One second less" }));
    expect(screen.getByText("3 seconds")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "One second less" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect((await saves(update)).scenes[0]?.fields.seconds).toBe(3);
  });

  it("changes a look on one scene, then on every scene", async () => {
    const { update } = rig();
    fireEvent.click(screen.getByRole("radio", { name: "Looks" }));
    fireEvent.click(screen.getByRole("button", { name: "sage" }));
    expect((await saves(update)).scenes.map((s) => s.fields.theme)).toEqual(["sage", "paper"]);
    fireEvent.click(screen.getByRole("button", { name: "Use this look on every scene" }));
    expect((await saves(update)).scenes.map((s) => s.fields.theme)).toEqual(["sage", "sage"]);
  });

  it("saves what was typed before making the video, and follows the render", async () => {
    const { update, api } = rig();
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "Last words" } });
    fireEvent.click(screen.getByRole("button", { name: "Make the video" }));
    await waitFor(() => expect(api.render).toHaveBeenCalled());
    expect(update).toHaveBeenCalledTimes(1);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Checking the words on the screen…")).toBeTruthy();
  });

  it("does not start a video when the last change could not be saved", async () => {
    const update = vi.fn(async () => {
      throw new Error("Scene 1: Write a title.");
    });
    const { api } = rig({ update } as never);
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Make the video" }));
    await waitFor(() => expect(update).toHaveBeenCalled());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(api.render).not.toHaveBeenCalled();
    expect(within(screen.getByRole("dialog")).getByText("Scene 1: Write a title.")).toBeTruthy();
  });
});
