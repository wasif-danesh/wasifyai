// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { BuilderProject, SceneDocument, VideoBuilderApi } from "@wasifyai/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatScreenProps } from "../../chat/ChatScreen";
import { ArrangeOverlay, laidOut, moved, placeOf, resized } from "./ArrangeOverlay";
import { type EditorAssistant, SceneEditor } from "./SceneEditor";
import { ScenesStart } from "./ScenesStart";
import { lengthOf, newSceneId, sceneAt, startOf, withWorkedOut } from "./use-scene-editor";

vi.mock("./vendor/hyperframes-player.global.js", () => ({}));

// the chat has its own tests: here, what the editor gives it and does with what it reports
let chat: ChatScreenProps;
vi.mock("../../chat/ChatScreen", () => ({
  ChatScreen: (props: ChatScreenProps) => {
    chat = props;
    return <div>The chat</div>;
  },
}));

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

  it("hears the player even when its address comes after its script", async () => {
    let answer: (a: { url: string; expires_at: number }) => void = () => {};
    rig({
      live: vi.fn(
        () =>
          new Promise((go) => {
            answer = go;
          }),
      ),
    } as never);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    await act(async () =>
      answer({ url: "http://engine/live", expires_at: Date.now() / 1000 + 3600 }),
    );
    const player = await waitFor(() => {
      const found = document.querySelector("hyperframes-player");
      expect(found).toBeTruthy();
      return found as Element;
    });
    await act(async () => {
      player.dispatchEvent(new Event("play"));
    });
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
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
    const asked = screen.getByRole("dialog");
    fireEvent.click(within(asked).getByRole("radio", { name: "Draft" }));
    fireEvent.click(within(asked).getByRole("button", { name: "Make the video" }));
    await waitFor(() => expect(api.render).toHaveBeenCalledWith("p".repeat(32), "mp4", "draft"));
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
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Make the video" }),
    );
    await waitFor(() => expect(update).toHaveBeenCalled());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(api.render).not.toHaveBeenCalled();
    expect(within(screen.getByRole("dialog")).getByText("Scene 1: Write a title.")).toBeTruthy();
  });
});

describe("the assistant in the editor", () => {
  const ASSISTANT = { runs: {}, api: {}, images: {} } as unknown as EditorAssistant;
  const after: SceneDocument = {
    ...film,
    name: "After the assistant",
    scenes: [{ ...first, fields: { ...first.fields, title: "Changed by it" } }],
  };

  function docked(over: Partial<VideoBuilderApi> = {}, brief?: string) {
    const update = vi.fn(async (_id: string, slots: unknown) => project(slots as SceneDocument));
    const api = {
      update,
      live: vi.fn(async () => ({
        url: "http://engine/live",
        expires_at: Date.now() / 1000 + 3600,
      })),
      get: vi.fn(async () => project(after)),
      keepConversation: vi.fn(async () => {}),
      ...over,
    } as unknown as VideoBuilderApi;
    render(
      <SceneEditor
        api={api}
        project={{ ...project(), conversation_id: "c-1" }}
        catalogue={catalogue}
        onBack={() => {}}
        assistant={ASSISTANT}
        brief={brief}
      />,
    );
    return { api, update };
  }
  const changed = (id = "t1", output: Record<string, unknown> = {}) =>
    act(async () => {
      chat.onToolResult?.({
        id,
        name: "propose_action",
        status: "ok",
        output: { action_id: "motion.change_scene", ...output },
      });
    });

  it("tells the chat which project and scene, and reopens the project's own chat", () => {
    docked();
    expect(chat.conversationId).toBe("c-1");
    expect(chat.runInput).toEqual({
      working_on: {
        action_id: "motion.read_project",
        params: { composition_id: "p".repeat(32), scene_id: "aaaaaaaa" },
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /Scene 2, Proof/ }));
    const on = chat.runInput?.working_on as { params: { scene_id: string } };
    expect(on.params.scene_id).toBe("bbbbbbbb");
  });

  it("sends the brief once, with the chat in view", () => {
    docked({}, "A promo for tea");
    expect(chat.firstMessage).toBe("A promo for tea");
    expect(screen.getByText("The chat").closest("[hidden]")).toBeNull();
  });

  it("opens on the scene's details when there is no brief, keeping the chat alive", () => {
    docked();
    expect(screen.getByText("The chat").closest("[hidden]")).not.toBeNull();
    expect(screen.getByLabelText("Scene name")).toBeTruthy();
  });

  it("remembers a new chat with the project", async () => {
    const { api } = docked();
    await act(async () => chat.onConversation?.("c-2", "Title"));
    expect(api.keepConversation).toHaveBeenCalledWith("p".repeat(32), "c-2");
  });

  it("saves what was typed before the assistant reads the project", async () => {
    const { update } = docked();
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "Just typed" } });
    await act(async () => {
      await chat.beforeTurn?.();
    });
    const sent = update.mock.calls.at(-1)?.[1] as SceneDocument;
    expect(sent.scenes[0]?.fields.title).toBe("Just typed");
  });

  it("shows what the assistant changed, as one Undo step of its own", async () => {
    docked();
    await changed();
    await waitFor(() =>
      expect((screen.getByLabelText("Project name") as HTMLInputElement).value).toBe(
        "After the assistant",
      ),
    );
    expect((screen.getByLabelText(/^Title/) as HTMLInputElement).value).toBe("Changed by it");
    fireEvent.click(screen.getByRole("button", { name: "Undo: The assistant's change" }));
    expect((screen.getByLabelText(/^Title/) as HTMLInputElement).value).toBe("First");
  });

  it("goes to the scene the assistant just added", async () => {
    const added = { ...after, scenes: [first, { ...first, id: "cccccccc" }] };
    docked({ get: vi.fn(async () => project(added)) } as never);
    await changed("t1", { scene_id: "cccccccc" });
    await waitFor(() => expect(screen.getByText("Scene 2 of 2")).toBeTruthy());
  });

  it("does not read the project back for what changes nothing, or what failed", async () => {
    const { api } = docked();
    await act(async () => {
      chat.onToolResult?.({
        id: "a",
        name: "propose_action",
        status: "ok",
        output: { action_id: "video_builder.render" },
      });
      chat.onToolResult?.({
        id: "b",
        name: "propose_action",
        status: "refused",
        output: { action_id: "motion.change_scene" },
      });
    });
    expect(api.get).not.toHaveBeenCalled();
  });

  it("undoes from the change's own card, also what came after it", async () => {
    docked();
    await changed("t1");
    await waitFor(() => expect(chat.undoOfTool?.("t1")?.undone).toBe(false));
    expect(chat.undoOfTool?.("from-an-earlier-visit")).toBeNull();
    await act(async () => chat.undoOfTool?.("t1")?.undo());
    expect(chat.undoOfTool?.("t1")?.undone).toBe(true);
    expect((screen.getByLabelText(/^Title/) as HTMLInputElement).value).toBe("First");
  });

  it("keeps the person out of the project while the assistant works", async () => {
    docked();
    await act(async () => chat.onWorking?.(true));
    expect(
      (screen.getByRole("button", { name: "Make the video" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByLabelText("Scene name").closest("[inert]")).not.toBeNull();
    await act(async () => chat.onWorking?.(false));
    expect(screen.getByLabelText("Scene name").closest("[inert]")).toBeNull();
  });
});

describe("the first screen", () => {
  it("sends the brief with a starting point and the shape", () => {
    const onBrief = vi.fn();
    render(
      <ScenesStart
        catalogue={catalogue}
        onBrief={onBrief}
        onEmpty={() => {}}
        onOneGraphic={() => {}}
      />,
    );
    expect(
      (screen.getByRole("button", { name: "Make a first version" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.change(screen.getByLabelText("Describe your video"), {
      target: { value: "Our new tea." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sale or offer" }));
    fireEvent.click(screen.getByRole("radio", { name: "1:1" }));
    fireEvent.click(screen.getByRole("button", { name: "Make a first version" }));
    expect(onBrief).toHaveBeenCalledWith(
      "A short video about an offer, clear about what it is. Our new tea.",
      "square",
      undefined,
    );
  });

  it("can start empty, or make just one graphic", () => {
    const onEmpty = vi.fn();
    const onOne = vi.fn();
    render(
      <ScenesStart
        catalogue={catalogue}
        onBrief={() => {}}
        onEmpty={onEmpty}
        onOneGraphic={onOne}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Start empty" }));
    expect(onEmpty).toHaveBeenCalledWith("portrait");
    fireEvent.click(screen.getByRole("button", { name: "Quote" }));
    expect(onOne).toHaveBeenCalledWith("quote");
  });
});

describe("arranging on the preview", () => {
  const box = { x: 20, y: 30, w: 60, h: 10 };
  const place = { x: 20, y: 30, w: 60, scale: 1 };

  it("works out moves that stay on the picture", () => {
    expect(placeOf(box)).toEqual(place);
    expect(placeOf(box, { ...place, x: 5 }).x).toBe(5);
    expect(moved(place, 10, 5, -5)).toEqual({ ...place, x: 25, y: 25 });
    expect(moved(place, 10, 500, 500)).toEqual({ ...place, x: 40, y: 90 });
    expect(moved(place, 10, -500, -500)).toEqual({ ...place, x: 0, y: 0 });
  });

  it("makes letters grow with the box, within limits", () => {
    expect(resized(place, 15)).toEqual({ ...place, w: 75, scale: 1.25 });
    expect(resized(place, 500).x).toBe(20);
    expect(resized(place, 500).w).toBe(80);
    expect(resized({ ...place, scale: 2.9 }, 30).scale).toBe(3);
  });

  it("moves the words together for a layout, leaving the caption", () => {
    const parts = {
      bar: { x: 40, y: 40, w: 20, h: 2 },
      title: { x: 10, y: 45, w: 80, h: 10 },
      subtitle: { x: 0, y: 0, w: 0, h: 0 },
      caption: { x: 8, y: 90, w: 84, h: 5 },
    };
    const top = laidOut("top", parts, {});
    expect(top.bar?.y).toBe(10);
    expect(top.title?.y).toBe(15);
    expect(top.caption).toBeUndefined();
    expect(top.subtitle).toBeUndefined();
    expect(laidOut("bottom", parts, {}).title?.y).toBe(80);
    expect(laidOut("middle", parts, {}).bar?.y).toBe(42.5);
    expect(laidOut("top", {}, { title: place })).toEqual({ title: place });
  });

  function overlay(placed = {}) {
    const onLive = vi.fn();
    const onCommit = vi.fn();
    render(
      <ArrangeOverlay
        ratio={1}
        parts={{ title: box }}
        placed={placed}
        onLive={onLive}
        onCommit={onCommit}
      />,
    );
    return { onLive, onCommit, part: screen.getByRole("button", { name: /Move the title/ }) };
  }

  it("moves with the arrow keys, further with shift, and resizes with plus and minus", () => {
    const { onCommit, part } = overlay();
    fireEvent.keyDown(part, { key: "ArrowRight" });
    expect(onCommit).toHaveBeenLastCalledWith("title", { ...place, x: 21 }, "arrange:title");
    fireEvent.keyDown(part, { key: "ArrowDown", shiftKey: true });
    expect(onCommit).toHaveBeenLastCalledWith("title", { ...place, y: 35 }, "arrange:title");
    fireEvent.keyDown(part, { key: "+" });
    expect(onCommit.mock.lastCall?.[1].scale).toBe(1.05);
    fireEvent.keyDown(part, { key: "a" });
    expect(onCommit).toHaveBeenCalledTimes(3);
  });

  it("says when a part is too close to the edge for a video to be made", () => {
    render(
      <ArrangeOverlay
        ratio={16 / 9}
        parts={{ title: { x: 20, y: 3, w: 60, h: 10 }, subtitle: box }}
        placed={{}}
        onLive={() => {}}
        onCommit={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /Move the title.*too close/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /under the title.*too close/ })).toBeNull();
  });

  it("does not catch keys or draw boxes for what the page has not reported", () => {
    render(
      <ArrangeOverlay ratio={1} parts={null} placed={{}} onLive={() => {}} onCommit={() => {}} />,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers the layouts, and going back to the design", () => {
    const update = vi.fn(async (_id: string, slots: unknown) => project(slots as SceneDocument));
    const api = {
      update,
      live: vi.fn(async () => ({ url: "x", expires_at: Date.now() / 1000 + 3600 })),
    } as unknown as VideoBuilderApi;
    const placedFilm = { ...film, scenes: [{ ...first, arrange: { title: place } }] };
    render(
      <SceneEditor
        api={api}
        project={project(placedFilm)}
        catalogue={catalogue}
        onBack={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "As designed" }));
    expect(screen.getByRole("button", { name: "Undo: Back to the design" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Arrange" })).toBeTruthy();
  });
});

describe("a project's files", () => {
  const picture = {
    id: "aaaa0000", kind: "image" as const, name: "can.jpg", file: "aaaa0000.jpg", seconds: 0,
    width: 10, height: 10, has_audio: false, codec: "",
  }; // biome-ignore format: a sample
  const clip = {
    id: "bbbb0000", kind: "video" as const, name: "pour.mp4", file: "bbbb0000.mp4", seconds: 8,
    width: 10, height: 10, has_audio: true, codec: "hevc",
  }; // biome-ignore format: a sample
  const song = {
    id: "cccc0000", kind: "audio" as const, name: "song.m4a", file: "cccc0000.m4a", seconds: 8,
    width: 0, height: 0, has_audio: false, codec: "aac",
  }; // biome-ignore format: a sample

  function withFiles(assets = [picture, clip, song]) {
    const update = vi.fn(async (_id: string, slots: unknown) =>
      project({ ...(slots as SceneDocument), assets }),
    );
    const api = {
      update,
      live: vi.fn(async () => ({
        url: "http://engine/live/t/index.html",
        expires_at: Date.now() / 1000 + 3600,
      })),
      addAsset: vi.fn(async () => ({ asset: picture, assets: [...assets, picture] })),
      removeAsset: vi.fn(async () => project({ ...film, assets: [] })),
    } as unknown as VideoBuilderApi;
    render(
      <SceneEditor
        api={api}
        project={project({ ...film, assets })}
        catalogue={catalogue}
        onBack={() => {}}
      />,
    );
    return { api, update };
  }
  const tool = (name: string) => fireEvent.click(screen.getByRole("radio", { name }));

  describe("making something for a scene", () => {
    const voiceover = {
      id: "dddd0000", kind: "audio" as const, name: "Try it.wav", file: "dddd0000.wav", seconds: 40,
      width: 0, height: 0, has_audio: false, codec: "pcm_s16le",
    }; // biome-ignore format: a sample
    const cues = [{ text: "Try it.", start: 0.2, end: 1 }];

    function maker(make: VideoBuilderApi["make"], more: Partial<VideoBuilderApi> = {}) {
      const update = vi.fn(async (_id: string, slots: unknown) => project(slots as SceneDocument));
      const api = {
        update,
        live: vi.fn(async () => ({
          url: "http://engine/live/t/index.html",
          expires_at: Date.now() / 1000 + 3600,
        })),
        voices: vi.fn(async () => [{ id: "v1", name: "Warm" }]),
        make,
        ...more,
      } as unknown as VideoBuilderApi;
      render(
        <SceneEditor api={api} project={project(film)} catalogue={catalogue} onBack={() => {}} />,
      );
      fireEvent.click(screen.getByRole("radio", { name: "Make" }));
      return { update };
    }
    const lastSaved = async (update: ReturnType<typeof vi.fn>) => {
      await waitFor(() => expect(update).toHaveBeenCalled(), { timeout: 2000 });
      return update.mock.calls.at(-1)?.[1] as SceneDocument;
    };

    it("puts a voiceover on the scene with its captions and makes the scene long enough", async () => {
      const make = vi.fn(async () => ({
        state: "done" as const, asset: voiceover, assets: [voiceover], cues,
      })); // biome-ignore format: a sample
      const { update } = maker(make);
      fireEvent.click(screen.getByRole("radio", { name: "Speech" }));
      fireEvent.change(screen.getByLabelText("What should it say?"), {
        target: { value: "Try it." },
      });
      fireEvent.change(await screen.findByLabelText("Voice"), { target: { value: "v1" } });
      fireEvent.click(screen.getByRole("button", { name: "Make the voiceover" }));
      await waitFor(() =>
        expect(make).toHaveBeenCalledWith("p".repeat(32), {
          what: "speech", text: "Try it.", captions: true, voice: "v1",
        }),
      ); // biome-ignore format: a sample
      const saved = await lastSaved(update);
      const scene = saved.scenes[0];
      expect(scene?.sound).toEqual({ asset: "dddd0000", volume: 1, loop: false });
      expect(scene?.cues).toEqual(cues);
      expect(scene?.fields.seconds).toBe(40);
      expect(saved.assets).toEqual([voiceover]);
    });

    it("takes it off with one Undo and keeps the file in the project", async () => {
      const make = vi.fn(async () => ({
        state: "done" as const, asset: voiceover, assets: [voiceover], cues,
      })); // biome-ignore format: a sample
      const { update } = maker(make);
      fireEvent.click(screen.getByRole("radio", { name: "Speech" }));
      fireEvent.change(screen.getByLabelText("What should it say?"), {
        target: { value: "Try it." },
      });
      fireEvent.click(screen.getByRole("button", { name: "Make the voiceover" }));
      await lastSaved(update);
      update.mockClear();
      fireEvent.click(screen.getByRole("button", { name: /^Undo/ }));
      const back = await lastSaved(update);
      expect(back.scenes[0]?.sound ?? null).toBeNull();
      expect(back.scenes[0]?.fields.seconds).not.toBe(40);
      expect(back.assets).toEqual([voiceover]);
    });

    it("says why it could not be made and keeps what was typed", async () => {
      const make = vi.fn(async () => {
        throw new Error("Set up the speech models first.");
      });
      const { update } = maker(make);
      fireEvent.click(screen.getByRole("radio", { name: "Speech" }));
      fireEvent.change(screen.getByLabelText("What should it say?"), {
        target: { value: "Try it." },
      });
      fireEvent.click(screen.getByRole("button", { name: "Make the voiceover" }));
      expect(await screen.findByText(/Set up the speech models first/)).toBeTruthy();
      expect((screen.getByLabelText("What should it say?") as HTMLTextAreaElement).value).toBe(
        "Try it.",
      );
      expect(update).not.toHaveBeenCalled();
    });

    it("follows a long make, and stopping it leaves the project as it was", async () => {
      const make = vi.fn(async () => ({ state: "working" as const, job_id: "j1", progress: 0.25 }));
      const stopMake = vi.fn(async () => ({ state: "stopped" as const }));
      const makeStatus = vi.fn(async () => ({ state: "working" as const, job_id: "j1" }));
      const { update } = maker(make, { stopMake, makeStatus });
      fireEvent.change(screen.getByLabelText("What should it show?"), {
        target: { value: "A can" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Make the picture" }));
      expect(await screen.findByText(/Making the picture… 25%/)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Stop" }));
      expect(await screen.findByRole("button", { name: "Make the picture" })).toBeTruthy();
      await waitFor(() => expect(stopMake).toHaveBeenCalledWith("j1"), { timeout: 3000 });
      expect(update).not.toHaveBeenCalled();
    });

    it("puts a made picture behind the scene or on it", async () => {
      const made = {
        id: "eeee0000", kind: "image" as const, name: "A can.jpg", file: "eeee0000.jpg", seconds: 0,
        width: 10, height: 10, has_audio: false, codec: "",
      }; // biome-ignore format: a sample
      const make = vi.fn(async () => ({
        state: "done" as const, asset: made, assets: [made], cues: [],
      })); // biome-ignore format: a sample
      const { update } = maker(make);
      fireEvent.change(screen.getByLabelText("What should it show?"), {
        target: { value: "A can" },
      });
      fireEvent.click(screen.getByRole("radio", { name: "On the scene" }));
      fireEvent.click(screen.getByRole("button", { name: "Make the picture" }));
      const saved = await lastSaved(update);
      expect(saved.scenes[0]?.images).toEqual([{ asset: "eeee0000" }]);
    });
  });
  const saved = async (update: ReturnType<typeof vi.fn>) => {
    await waitFor(() => expect(update).toHaveBeenCalled(), { timeout: 2000 });
    return update.mock.calls.at(-1)?.[1] as SceneDocument;
  };

  it("uses a picture as a background and places it on a scene", async () => {
    const { update } = withFiles();
    tool("Media");
    fireEvent.click(screen.getByRole("button", { name: "can.jpg" }));
    fireEvent.click(screen.getByRole("button", { name: "Use as background" }));
    fireEvent.click(screen.getByRole("button", { name: "Place on scene" }));
    const sent = await saved(update);
    expect(sent.scenes[0]?.background?.asset).toBe("aaaa0000");
    expect(sent.scenes[0]?.images).toEqual([{ asset: "aaaa0000" }]);
    expect(screen.getByText("Behind: can.jpg")).toBeTruthy();
    expect(screen.getByText("Placed: can.jpg")).toBeTruthy();
  });

  it("says when a clip may not play in the preview, and offers its trim and its sound", async () => {
    withFiles();
    tool("Media");
    fireEvent.click(screen.getByRole("button", { name: "pour.mp4" }));
    expect(screen.getByText(/This clip is hevc/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Place on scene" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Use as background" }));
    expect(screen.getByLabelText(/Starts 0 seconds in/)).toBeTruthy();
    expect(screen.getByLabelText("Its own sound")).toBeTruthy();
  });

  it("gives a scene its own sound, and the whole video its music", async () => {
    const { update } = withFiles();
    tool("Sound");
    fireEvent.click(screen.getAllByRole("button", { name: "song.m4a" })[0] as HTMLElement);
    expect(screen.getByLabelText("Repeat it to fill the scene")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "song.m4a" }).at(-1) as HTMLElement);
    const sent = await saved(update);
    expect(sent.scenes[0]?.sound?.asset).toBe("cccc0000");
    expect(sent.soundtrack).toEqual({ asset: "cccc0000", volume: 0.4, loop: true, start: 0 });
    expect(screen.getByLabelText("Repeat")).toBeTruthy();
  });

  it("adds a file from this computer, and says why when it cannot", async () => {
    const { api } = withFiles();
    tool("Media");
    const file = new File(["x"], "new.png");
    fireEvent.change(screen.getByLabelText("Add a photo or clip"), { target: { files: [file] } });
    await waitFor(() => expect(api.addAsset).toHaveBeenCalledWith("p".repeat(32), file));
    (api.addAsset as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("Too big."));
    fireEvent.change(screen.getByLabelText("Add a photo or clip"), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Too big."));
  });

  it("removes a file from the project and from its scenes, as one Undo", async () => {
    const { api } = withFiles();
    tool("Media");
    fireEvent.click(screen.getByRole("button", { name: "can.jpg" }));
    fireEvent.click(screen.getByRole("button", { name: /Remove from the project/ }));
    await waitFor(() => expect(api.removeAsset).toHaveBeenCalledWith("p".repeat(32), "aaaa0000"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Undo: Remove a file" })).toBeTruthy(),
    );
  });
});
