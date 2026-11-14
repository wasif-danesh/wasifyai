// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CodeApi, CodeEvent, CodeSession, CodeTurn } from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Code } from "./Code";
import { buildThread, stepLine } from "./thread";

vi.mock("../chat/thread/markdown/Markdown", () => ({
  Markdown: ({ text }: { text: string }) => <div data-markdown="">{text}</div>,
}));

const FOLDER = "/Users/me/Projects/bakery-site";

function session(over: Partial<CodeSession> = {}): CodeSession {
  return {
    id: "s1",
    title: "bakery-site",
    folder: FOLDER,
    project: "bakery-site",
    mode: "plan",
    model: "claude-sonnet-5-5",
    state: "new",
    working: false,
    result: "",
    turns: 0,
    answer: "",
    ended: "",
    cost_usd: 0,
    cost_limit_usd: 0,
    tokens_in: 0,
    tokens_out: 0,
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-14T10:00:00Z",
    ...over,
  };
}

function turn(over: Partial<CodeTurn> = {}): CodeTurn {
  return {
    id: "t1",
    position: 1,
    request: "How would you add the opening hours?",
    state: "done",
    result: "",
    why: "finished",
    answer: "Here is the plan.",
    steps: 2,
    notes: [],
    started_at: "",
    finished_at: "",
    ...over,
  };
}

let seq = 0;
const ev = (e: Record<string, unknown>, run = "t1") =>
  ({ seq: ++seq, run_id: run, thread_id: "s1", ts: "", ...e }) as CodeEvent;

/** A stream the test feeds by hand. */
function feed() {
  const waiting: ((e: CodeEvent | null) => void)[] = [];
  const queued: (CodeEvent | null)[] = [];
  return {
    push(e: CodeEvent | null) {
      const next = waiting.shift();
      if (next) next(e);
      else queued.push(e);
    },
    async *events(): AsyncGenerator<CodeEvent> {
      for (;;) {
        const e =
          queued.length > 0
            ? (queued.shift() as CodeEvent | null)
            : await new Promise<CodeEvent | null>((r) => waiting.push(r));
        if (e === null) return;
        yield e;
      }
    },
  };
}

function api(over: Partial<CodeApi> = {}): CodeApi {
  return {
    engine: async () => ({ supported: true, installed: true, running: false }),
    models: async () => [
      {
        id: "claude-sonnet-5-5",
        title: "Claude Sonnet 5.5",
        where: "cloud",
        default: true,
        ready: true,
      },
    ],
    sessions: async () => [],
    session: async () => session(),
    turns: async () => [],
    start: async () => session(),
    send: async () => session({ working: true, state: "working" }),
    stop: async () => session(),
    remove: async () => undefined,
    files: async (_id: string, path = "") =>
      path === ""
        ? [
            { name: "src", path: "src", kind: "folder", bytes: 0 },
            { name: "README.md", path: "README.md", kind: "file", bytes: 20 },
          ]
        : [{ name: "site.js", path: "src/site.js", kind: "file", bytes: 12 }],
    file: async (_id: string, path: string) => ({
      path,
      bytes: 20,
      binary: false,
      text: "# Bakery site\nA small website.",
      lines: 2,
      cut: false,
    }),
    events: () => feed().events(),
    ...over,
  } as CodeApi;
}

const props = { pickFolder: async () => FOLDER, onOpenSetup: vi.fn(), onOpenKeys: vi.fn() };

afterEach(() => {
  seq = 0;
  vi.clearAllMocks();
});

describe("where coding lives", () => {
  it("says what the agent may and may not do, and what leaves this computer, before anything is read", async () => {
    render(<Code api={api()} {...props} />);
    expect(
      await screen.findByRole("heading", { name: "Build and fix code by asking" }),
    ).toBeTruthy();
    expect(screen.getByText("find and read every file")).toBeTruthy();
    expect(screen.getByText(/change, add or delete a file, or run a command/)).toBeTruthy();
    expect(screen.getByText(/sent to the model you chose: Claude Sonnet 5.5/)).toBeTruthy();
  });

  it("asks for the coding engine to be set up when it is not", async () => {
    const onOpenSetup = vi.fn();
    render(
      <Code
        api={api({ engine: async () => ({ supported: true, installed: false, running: false }) })}
        {...props}
        onOpenSetup={onOpenSetup}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Open Optional parts" }));
    expect(onOpenSetup).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Choose a folder/ })).toBeNull();
  });

  it("says what to do when no model is ready, and does not let a folder be chosen", async () => {
    const models = async () => [
      {
        id: "claude-sonnet-5-5",
        title: "Claude Sonnet 5.5",
        where: "cloud" as const,
        default: true,
        ready: false,
      },
    ];
    render(<Code api={api({ models })} {...props} />);
    expect(await screen.findByText("No model is ready for coding")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /Choose a folder/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("opens a session on the folder the person chose, and says why when it is refused", async () => {
    const start = vi.fn(async () => session());
    const { unmount } = render(<Code api={api({ start })} {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: /Choose a folder/ }));
    expect(start).toHaveBeenCalledWith({ folder: FOLDER, model: "claude-sonnet-5-5" });
    expect(
      await screen.findByRole("heading", { name: "What do you want to know about bakery-site?" }),
    ).toBeTruthy();
    unmount();
    const refused = vi.fn(async () => {
      throw new Error("Choose one project's folder, not the whole home folder or a disk.");
    });
    render(<Code api={api({ start: refused })} {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: /Choose a folder/ }));
    expect(await screen.findByText(/not the whole home folder/)).toBeTruthy();
  });

  it("lists the projects with their sessions, and deletes one only after a yes", async () => {
    const remove = vi.fn(async () => undefined);
    const sessions = async () => [
      session({ id: "s1", title: "Opening hours", turns: 2 }),
      session({ id: "s2", title: "The footer", working: true }),
      session({ id: "s3", title: "Look around", folder: "/Users/me/other", project: "other" }),
    ];
    render(<Code api={api({ sessions, remove })} {...props} />);
    expect(await screen.findByRole("heading", { name: "Projects" })).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toContain(
      "other",
    );
    expect(screen.getByText("2 asked")).toBeTruthy();
    expect(screen.getByText("Working")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Delete the session Opening hours" }));
    expect(remove).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/The folder and its files are not touched/)).toBeTruthy();
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(remove).toHaveBeenCalledWith("s1");
  });
});

describe("a session in Plan", () => {
  it("sends what was asked, shows the agent's steps and its answer, and says nothing was changed", async () => {
    const stream = feed();
    const send = vi.fn(async () => session({ working: true, state: "working" }));
    let done = false;
    const turns = async () =>
      done ? [turn()] : [turn({ state: "working", why: "", answer: "", steps: 0 })];
    render(
      <Code
        api={api({
          sessions: async () => [session()],
          send,
          turns,
          session: async () =>
            done ? session({ state: "done", turns: 1, cost_usd: 0.2 }) : session(),
          events: () => stream.events(),
        })}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    const box = await screen.findByRole("textbox", { name: "Ask about this project" });
    expect(screen.getByText("Plan")).toBeTruthy();
    await userEvent.type(box, "How would you add the opening hours?{Enter}");
    expect(send).toHaveBeenCalledWith("s1", "How would you add the opening hours?");
    expect(await screen.findByRole("button", { name: "Stop" })).toBeTruthy();
    stream.push(ev({ event: "code_state", state: "working", cost_usd: 0 }));
    stream.push(
      ev({ event: "tool_call", id: "c1", name: "glob", arguments: { pattern: "**/*.html" } }),
    );
    stream.push(
      ev({
        event: "tool_result",
        id: "c1",
        name: "glob",
        status: "ok",
        output: { text: "home.html" },
      }),
    );
    stream.push(ev({ event: "token", node: "agent", text: "Here is " }));
    expect(await screen.findByText("Looked for files named **/*.html")).toBeTruthy();
    expect(await screen.findByText("Here is")).toBeTruthy();
    done = true;
    stream.push(ev({ event: "code_message", text: "Here is the plan." }));
    stream.push(ev({ event: "code_state", state: "done", why: "finished", cost_usd: 0.2 }));
    expect(await screen.findByText("Here is the plan.")).toBeTruthy();
    expect(await screen.findByText("Nothing was changed")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("$0.20")).toBeTruthy());
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
    expect(screen.getByText("Plan · nothing is changed")).toBeTruthy();
  }, 20_000);

  it("stops the turn when Stop is chosen", async () => {
    const stop = vi.fn(async () => session({ state: "done", ended: "stopped" }));
    render(
      <Code
        api={api({
          sessions: async () => [session({ working: true, state: "working" })],
          session: async () => session({ working: true, state: "working" }),
          turns: async () => [turn({ state: "working", why: "", answer: "" })],
          stop,
        })}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop" }));
    expect(stop).toHaveBeenCalledWith("s1");
  });

  it("shows an older turn from what was kept: the request, the answer and how many steps", async () => {
    render(
      <Code
        api={api({
          sessions: async () => [session({ turns: 1, state: "done" })],
          session: async () => session({ turns: 1, state: "done" }),
          turns: async () => [turn()],
        })}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    expect(await screen.findByText("How would you add the opening hours?")).toBeTruthy();
    expect(screen.getByText("Here is the plan.")).toBeTruthy();
    expect(screen.getByText("The agent took 2 steps in the project.")).toBeTruthy();
  });
});

describe("the thread", () => {
  const turns = [turn({ state: "working", why: "", answer: "", steps: 0 })];

  it("groups steps, replaces the words being written by the finished message, and ends once", () => {
    const thread = buildThread(turns, [
      ev({ event: "code_state", state: "working", cost_usd: 0 }),
      ev({ event: "tool_call", id: "a", name: "glob", arguments: { pattern: "*.py" } }),
      ev({
        event: "tool_call",
        id: "b",
        name: "planning_file_editor",
        arguments: { command: "view", path: "/p/a/b/c/app.py" },
      }),
      ev({
        event: "tool_result",
        id: "b",
        name: "planning_file_editor",
        status: "error",
        output: { text: "no" },
      }),
      ev({ event: "token", node: "agent", text: "It " }),
      ev({ event: "token", node: "agent", text: "is" }),
      ev({ event: "code_message", text: "It is a shop." }),
      ev({ event: "code_state", state: "done", why: "finished", cost_usd: 0.1 }),
    ]);
    expect(thread).toHaveLength(1);
    const [only] = thread;
    expect(only?.parts.map((p) => p.kind)).toEqual(["steps", "message"]);
    expect(only?.parts[1]).toEqual({ kind: "message", text: "It is a shop.", writing: false });
    expect(only?.steps).toBe(2);
    expect(only?.working).toBe(false);
    expect(only?.ended).toBe("finished");
    const steps = only?.parts[0]?.kind === "steps" ? only.parts[0].steps : [];
    expect(steps.map((s) => s.status)).toEqual(["started", "error"]);
    expect(stepLine(steps[1] ?? { tool: "", given: {} })).toBe("Read …/b/c/app.py");
  });

  it("shows a refusal once, in the model's own words, and an error with what the engine said", () => {
    const refused = buildThread(turns, [
      ev({ event: "code_message", text: "The model declined this request." }),
      ev({ event: "code_refusal", message: "The model declined this request." }),
      ev({ event: "code_state", state: "done", why: "refused", cost_usd: 0 }),
    ]);
    expect(refused[0]?.parts).toEqual([
      { kind: "refusal", message: "The model declined this request." },
    ]);
    const failed = buildThread(turns, [
      ev({
        event: "code_state",
        state: "done",
        why: "error",
        detail: "The model is down.",
        cost_usd: 0,
      }),
    ]);
    expect(failed[0]?.ended).toBe("error");
    expect(failed[0]?.detail).toBe("The model is down.");
  });

  it("says each step in plain words", () => {
    expect(stepLine({ tool: "grep", given: { pattern: "TODO", path: "/p/src" } })).toBe(
      "Searched for “TODO” in /p/src",
    );
    expect(stepLine({ tool: "glob", given: {} })).toBe("Looked for files named anything");
    expect(
      stepLine({ tool: "planning_file_editor", given: { command: "create", path: "/p/x" } }),
    ).toBe("Tried to change /p/x");
  });
});

describe("the Files tab", () => {
  it("lists the project a folder at a time and opens a file to read, with nothing to change it", async () => {
    const file = vi.fn(async (_id: string, path: string) => ({
      path,
      bytes: 12,
      binary: false,
      text: "const a = 1;\nexport default a;",
      lines: 2,
      cut: false,
    }));
    render(
      <Code
        api={api({ sessions: async () => [session()], file } as Partial<CodeApi>)}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    const tree = await screen.findByRole("navigation", { name: "Files in bakery-site" });
    expect(await within(tree).findByRole("button", { name: "README.md" })).toBeTruthy();
    expect(screen.getByText("Choose a file to read it")).toBeTruthy();
    const folder = within(tree).getByRole("button", { name: "src" });
    expect(folder.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(folder);
    await userEvent.click(await within(tree).findByRole("button", { name: "site.js" }));
    expect(file).toHaveBeenCalledWith("s1", "src/site.js");
    expect(await screen.findByText("export default a;")).toBeTruthy();
    expect(screen.getByText("Read only. 2 lines.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /save|edit/i })).toBeNull();
  });

  it("says so when a file is not text", async () => {
    const file = async (_id: string, path: string) => ({
      path,
      bytes: 48_000,
      binary: true,
      text: "",
      lines: 0,
      cut: false,
    });
    render(
      <Code
        api={api({ sessions: async () => [session()], file } as Partial<CodeApi>)}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    await userEvent.click(await screen.findByRole("button", { name: "README.md" }));
    expect(await screen.findByText("This file is not text")).toBeTruthy();
  });
});
