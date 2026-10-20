// @vitest-environment jsdom
// Read aloud under a reply (ADR-0083, CU3), on both chat screens: opt-in, a visible speaking state, one passage ahead, nothing auto-plays.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  AssistantApi,
  ImagesApi,
  OnEvent,
  ParsedEvent,
  ReadAloudPart,
} from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatScreen } from "../ChatScreen";
import { ChatScreenNext } from "../ChatScreenNext";
import { createPlayer } from "./player";
import { type ReadAloudControl, languageNames } from "./use-read-aloud";

const ev = (event: string, data: Record<string, unknown> = {}): ParsedEvent =>
  ({ event, data: { run_id: "r1", seq: 1, ...data } }) as unknown as ParsedEvent;

const assistant: AssistantApi = {
  options: async () => ({ thinking: false }),
  searchStatus: async () => {
    throw new Error("unused");
  },
  updateSearch: async () => {
    throw new Error("unused");
  },
  setHead: async () => {},
  attach: async () => {
    throw new Error("unused");
  },
  unattach: async () => {},
  list: async () => [],
  get: async () => {
    throw new Error("unused");
  },
  rename: async () => {
    throw new Error("unused");
  },
  remove: async () => {},
};
const images = { get: async () => ({}) } as unknown as ImagesApi;

const REPLY = "Hello **there**, this is `the` answer.";

function runsReplying(...replies: string[]) {
  let n = 0;
  return {
    startRun: vi.fn(async (_p: string, _i: object, _s: AbortSignal, on: OnEvent) => {
      const text = replies[Math.min(n++, replies.length - 1)] ?? "";
      on(ev("token", { text }));
      on(ev("done", { outputs: { status: "done", conversation_id: "c1", title: "Hi" } }));
    }),
    watchRun: vi.fn(async () => {}),
  };
}

const part = (over: Partial<ReadAloudPart> = {}): ReadAloudPart => ({
  wav: new Blob(["RIFF"], { type: "audio/wav" }),
  part: 0,
  parts: 1,
  truncated: false,
  seconds: 2,
  model: "kokoro-82m",
  displaced: null,
  ...over,
});

/** A player that plays until the test says a passage has ended. */
function fakePlayer() {
  let finish: (() => void) | null = null;
  const player = {
    unlock: vi.fn(),
    play: vi.fn(
      (_wav: Blob) =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    ),
    stop: vi.fn(() => finish?.()),
  };
  return { player, end: () => finish?.() };
}

function control(over: Partial<ReadAloudControl> = {}) {
  const fp = fakePlayer();
  const speak = vi.fn(async (_t: string, _p: number, _s: AbortSignal) => part());
  const c: ReadAloudControl = { speak, player: () => fp.player, ...over };
  return { c, speak, ...fp };
}

type Screen = typeof ChatScreen | typeof ChatScreenNext;
async function shown(S: Screen, c: ReadAloudControl | undefined, ...replies: string[]) {
  const runs = runsReplying(...(replies.length ? replies : [REPLY]));
  const user = userEvent.setup();
  const view = render(
    <S
      runs={runs}
      assistant={assistant}
      images={images}
      composerOptions={{ readAloud: c }}
      examples={[]}
    />,
  );
  return { user, runs, view };
}
async function ask(user: ReturnType<typeof userEvent.setup>, words = "Hi") {
  await user.type(await screen.findByRole("textbox", { name: "Message" }), `${words}{Enter}`);
}

beforeEach(() => localStorage.clear());

describe.each([
  ["classic", ChatScreen],
  ["next", ChatScreenNext],
] as const)("read aloud on the %s chat", (_name, S) => {
  it("has no button where the engine has no voice to offer", async () => {
    const { user } = await shown(S, undefined);
    await ask(user);
    await screen.findByText(/this is/);
    expect(screen.queryByRole("button", { name: /aloud/i })).toBeNull();
  });

  it("never plays by itself: a finished reply only gets a button", async () => {
    const k = control();
    const { user } = await shown(S, k.c);
    await ask(user);
    expect(await screen.findByRole("button", { name: "Read this reply aloud" })).toBeEnabled();
    expect(k.speak).not.toHaveBeenCalled();
    expect(k.player.unlock).not.toHaveBeenCalled();
    expect(k.player.play).not.toHaveBeenCalled();
  });

  it("speaks the reply when pressed, says so in words, and goes back when it ends", async () => {
    const k = control();
    const { user } = await shown(S, k.c);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    expect(k.player.unlock).toHaveBeenCalledTimes(1); // inside the click
    await waitFor(() => expect(k.player.play).toHaveBeenCalledTimes(1));
    const [text, partNo, signal] = k.speak.mock.calls[0] ?? [];
    expect(text).toContain("this is"); // the reply as the model wrote it: the engine makes it plain words
    expect(partNo).toBe(0);
    expect(signal).toBeInstanceOf(AbortSignal);
    const stop = screen.getByRole("button", { name: "Stop reading aloud" });
    expect(stop).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("Reading aloud")).toBeInTheDocument();

    await act(async () => k.end());
    expect(await screen.findByRole("button", { name: "Read this reply aloud" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.queryByText("Reading aloud")).toBeNull();
  });

  it("Stop stops the sound and the request", async () => {
    const k = control();
    const { user } = await shown(S, k.c);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    await waitFor(() => expect(k.player.play).toHaveBeenCalled());
    const signal = k.speak.mock.calls[0]?.[2] as AbortSignal;
    await user.click(screen.getByRole("button", { name: "Stop reading aloud" }));
    expect(k.player.stop).toHaveBeenCalled();
    expect(signal.aborted).toBe(true);
    expect(
      await screen.findByRole("button", { name: "Read this reply aloud" }),
    ).toBeInTheDocument();
    expect(k.speak).toHaveBeenCalledTimes(1); // nothing was asked for after Stop
  });

  it("asks for the next passage while the first plays, and says which one it is on", async () => {
    const k = control();
    k.speak.mockImplementation(async (_t, n) => part({ part: n, parts: 3 }));
    const { user } = await shown(S, k.c);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    await waitFor(() => expect(k.player.play).toHaveBeenCalledTimes(1));
    expect(k.speak.mock.calls.map((c) => c[1])).toEqual([0, 1]); // passage 1 is fetched during passage 0
    expect(await screen.findByText("Reading aloud · 1 of 3")).toBeInTheDocument();
    await act(async () => k.end());
    await waitFor(() => expect(k.player.play).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Reading aloud · 2 of 3")).toBeInTheDocument();
    await act(async () => k.end());
    await waitFor(() => expect(k.player.play).toHaveBeenCalledTimes(3));
    expect(k.speak.mock.calls.map((c) => c[1])).toEqual([0, 1, 2]); // never past the last
    await act(async () => k.end());
    expect(
      await screen.findByRole("button", { name: "Read this reply aloud" }),
    ).toBeInTheDocument();
  });

  it("says it takes a moment before the first sound", async () => {
    const k = control();
    let release: (p: ReadAloudPart) => void = () => {};
    k.speak.mockImplementation(
      () =>
        new Promise<ReadAloudPart>((r) => {
          release = r;
        }),
    );
    const { user } = await shown(S, k.c);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    expect(await screen.findByText("Getting ready to read…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop reading aloud" })).toBeInTheDocument();
    await act(async () => release(part()));
    expect(await screen.findByText("Reading aloud")).toBeInTheDocument();
  });

  it("only one reply is read at a time", async () => {
    const k = control();
    const { user } = await shown(S, k.c, "First answer here.", "Second answer there.");
    await ask(user, "one");
    await screen.findByText("First answer here.");
    await ask(user, "two");
    await screen.findByText("Second answer there.");
    const buttons = await screen.findAllByRole("button", { name: "Read this reply aloud" });
    expect(buttons).toHaveLength(2);
    await user.click(buttons[0] as HTMLElement);
    await waitFor(() => expect(k.player.play).toHaveBeenCalledTimes(1));
    await user.click(buttons[1] as HTMLElement);
    await waitFor(() => expect(k.player.play).toHaveBeenCalledTimes(2));
    expect(k.player.stop).toHaveBeenCalled(); // the first one was stopped
    expect(k.speak.mock.calls.at(-1)?.[0]).toContain("Second answer");
    expect(screen.getAllByRole("button", { name: "Stop reading aloud" })).toHaveLength(1);
  });

  it("says the engine's sentence when it cannot read, as plain text", async () => {
    const k = control();
    k.speak.mockRejectedValue(new Error("The voice is busy <img src=x onerror=alert(1)>."));
    const { user } = await shown(S, k.c);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    const card = await screen.findByRole("alert");
    expect(card).toHaveTextContent("The voice is busy <img src=x onerror=alert(1)>.");
    expect(card.querySelector("img")).toBeNull(); // shown as words, not made into an element
    expect(screen.getByRole("button", { name: "Read this reply aloud" })).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says when the sound cannot be played", async () => {
    const k = control();
    k.player.play.mockRejectedValue(
      new Error("This window did not allow sound. Press Read aloud again."),
    );
    const { user } = await shown(S, k.c);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("did not allow sound");
  });

  it("tells a long reply is only read from its start, and when the chat model was put away", async () => {
    const k = control();
    k.speak.mockResolvedValue(part({ truncated: true, displaced: "chat" }));
    const { user } = await shown(S, k.c);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    const note = await screen.findByText(/only the first part is read aloud/);
    expect(note).toHaveTextContent("put away to make room");
  });

  it("stops the sound and the request when the screen goes away", async () => {
    const k = control();
    const { user, view } = await shown(S, k.c);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    await waitFor(() => expect(k.player.play).toHaveBeenCalled());
    const signal = k.speak.mock.calls[0]?.[2] as AbortSignal;
    expect(signal.aborted).toBe(false);
    view.unmount();
    expect(k.player.stop).toHaveBeenCalled();
    expect(signal.aborted).toBe(true);
  });

  it("offers a setup card first when there is no voice, asks before anything is fetched, then is ready", async () => {
    const run = vi.fn(async (onProgress: (f: number | null) => void) => {
      onProgress(0.5);
    });
    const k = control({
      setup: {
        title: "Kokoro 82M",
        licence: "Apache-2.0",
        from: "huggingface.co",
        bytes: 189_549_408,
        languages: ["en-US", "en-GB"],
        run,
      },
    });
    const { user } = await shown(S, k.c);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    const card = await screen.findByRole("region", { name: "Set up read aloud" });
    expect(card).toHaveTextContent("Kokoro 82M");
    expect(card).toHaveTextContent("Apache-2.0");
    expect(card).toHaveTextContent("huggingface.co");
    expect(card).toHaveTextContent("190 MB");
    expect(card).toHaveTextContent(/English/);
    expect(run).not.toHaveBeenCalled(); // nothing is fetched before the click
    expect(k.speak).not.toHaveBeenCalled();
    expect(k.player.play).not.toHaveBeenCalled();
    await user.click(within(card).getByRole("button", { name: "Not now" }));
    expect(screen.queryByRole("region", { name: "Set up read aloud" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Read this reply aloud" }));
    await user.click(
      within(await screen.findByRole("region", { name: "Set up read aloud" })).getByRole("button", {
        name: /^Download/,
      }),
    );
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("shows why a setup failed, in words", async () => {
    const k = control({
      setup: {
        title: "Kokoro 82M",
        licence: "Apache-2.0",
        from: "",
        bytes: 1,
        run: async () => {
          throw new Error("The voice could not be downloaded. Try again.");
        },
      },
    });
    const { user } = await shown(S, k.c);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "Read this reply aloud" }));
    await user.click(await screen.findByRole("button", { name: /^Download/ }));
    expect(
      await screen.findByText("The voice could not be downloaded. Try again."),
    ).toBeInTheDocument();
  });
});

describe("the names of languages", () => {
  it("are words where the browser knows them and the code where it does not", () => {
    expect(languageNames(["en-US"])).toMatch(/English/);
    expect(languageNames(["zz-not-a-code!"])).toBe("zz-not-a-code!");
    expect(languageNames([])).toBe("");
    expect(languageNames(undefined)).toBe("");
  });
});

describe("the player", () => {
  it("unlocks one element in the click and plays each passage on it, releasing every sound", async () => {
    const made: string[] = [];
    const revoked: string[] = [];
    const elements: FakeAudio[] = [];
    class FakeAudio {
      src = "";
      volume = 1;
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        elements.push(this);
      }
      play = vi.fn(async () => {});
      pause = vi.fn();
      removeAttribute(name: string) {
        if (name === "src") this.src = "";
      }
    }
    vi.stubGlobal("Audio", FakeAudio);
    let n = 0;
    vi.stubGlobal("URL", {
      createObjectURL: () => {
        const u = `blob:${n++}`;
        made.push(u);
        return u;
      },
      revokeObjectURL: (u: string) => revoked.push(u),
    });
    const p = createPlayer();
    p.unlock();
    expect(elements).toHaveLength(1);
    expect(elements[0]?.volume).toBe(0); // the unlocking sound is silent
    const first = p.play(new Blob(["a"]));
    expect(elements).toHaveLength(1); // the same element
    expect(elements[0]?.volume).toBe(1);
    elements[0]?.onended?.();
    await first;
    const second = p.play(new Blob(["b"]));
    p.stop(); // resolves what is waiting
    await second;
    expect(new Set(revoked)).toEqual(new Set(made)); // nothing is kept
    vi.unstubAllGlobals();
  });

  it("says in words when the window blocks sound, and when the sound is broken", async () => {
    class Blocked {
      src = "";
      volume = 1;
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      play = vi.fn(async () => {
        throw new DOMException("no", "NotAllowedError");
      });
      pause = vi.fn();
      removeAttribute() {}
    }
    vi.stubGlobal("Audio", Blocked);
    vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => {} });
    await expect(createPlayer().play(new Blob(["a"]))).rejects.toThrow(/did not allow sound/);
    vi.unstubAllGlobals();
  });
});
