// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  CodeApi,
  CodeChange,
  CodeChangeFile,
  CodeEvent,
  CodeProject,
  CodeSession,
  CodeTurn,
} from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CARRY_OUT, Code } from "./Code";
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
    waiting: false,
    result: "",
    turns: 0,
    answer: "",
    ended: "",
    cost_usd: 0,
    cost_limit_usd: 5,
    model_calls: 0,
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
    changed: 0,
    undone: false,
    can_undo: false,
    can_redo: false,
    ...over,
  };
}

const PROJECT: CodeProject = {
  project: "bakery-site",
  folder: FOLDER,
  mode: "ask",
  kinds: [
    { id: "not_undoable", allowed: false, asked_now: true },
    { id: "delete", allowed: false, asked_now: false },
    { id: "install", allowed: false, asked_now: false },
  ],
};

const CHANGED_FILE: CodeChangeFile = {
  path: "src/home.html",
  what: "changed",
  test: false,
  binary: false,
  too_large: false,
  before: "<h1>Bakery</h1>\n<p>Welcome</p>\n",
  after: "<h1>Bakery</h1>\n<p>Open 9 to 5</p>\n",
  lines: [
    { t: "same", text: "<h1>Bakery</h1>", a: 1, b: 1 },
    { t: "del", text: "<p>Welcome</p>", a: 2 },
    { t: "add", text: "<p>Open 9 to 5</p>", b: 2 },
  ],
};

const CHANGE: CodeChange = {
  turn_id: "t1",
  position: 1,
  request: "Add the opening hours",
  started_at: "2026-11-14T14:02:00Z",
  undone: false,
  can_undo: true,
  can_redo: false,
  files: [
    { path: "src/home.html", what: "changed", test: false },
    { path: "tests/home.test.js", what: "added", test: true },
  ],
};

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
    find: async () => ({
      entries: [{ name: "site.js", path: "src/site.js", kind: "file", bytes: 0 }],
      more: false,
    }),
    setLimit: async (_id: string, usd: number) => session({ cost_limit_usd: usd }),
    setMode: async (_id: string, mode: CodeSession["mode"]) => session({ mode }),
    answer: async () => true,
    changes: async () => [],
    change: async () => CHANGED_FILE,
    undo: async (_id: string, turnId: string) => ({
      turn_id: turnId,
      undone: true,
      files: 2,
      own_changes: false,
      notes: [],
    }),
    redo: async (_id: string, turnId: string) => ({
      turn_id: turnId,
      undone: false,
      files: 2,
      own_changes: false,
      notes: [],
    }),
    project: async () => PROJECT,
    allow: async (_id: string, kind: string, allowed: boolean) => ({
      ...PROJECT,
      kinds: PROJECT.kinds.map((k) => (k.id === kind ? { ...k, allowed } : k)),
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
    expect(
      screen.getByText(/change and add files, in “Ask me” and “Work on its own”/),
    ).toBeTruthy();
    expect(screen.getByText(/run a command, a test or a program, or delete a file/)).toBeTruthy();
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
    // a project opened here starts in "Ask me"
    expect(start).toHaveBeenCalledWith({
      folder: FOLDER,
      model: "claude-sonnet-5-5",
      mode: "ask",
    });
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

describe("finding a file, the cost, and a session's address", () => {
  it("finds a file by part of its name and opens it", async () => {
    const find = vi.fn(async () => ({
      entries: [{ name: "site.js", path: "src/site.js", kind: "file" as const, bytes: 0 }],
      more: false,
    }));
    render(<Code api={api({ sessions: async () => [session()], find })} {...props} />);
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    await userEvent.type(
      await screen.findByRole("searchbox", { name: "Find a file by name" }),
      "site",
    );
    const results = await screen.findByRole("navigation", { name: "Files found" });
    expect(find).toHaveBeenCalledWith("s1", "site");
    await userEvent.click(within(results).getByRole("button", { name: /site\.js/ }));
    expect(await screen.findByText("Read only. 2 lines.")).toBeTruthy();
  });

  it("opens the cost to what it is made of, and changes the limit", async () => {
    const setLimit = vi.fn(async (_id: string, usd: number) =>
      session({ cost_usd: 0.21, model_calls: 14, turns: 3, cost_limit_usd: usd }),
    );
    const open = session({ cost_usd: 0.21, model_calls: 14, turns: 3 });
    render(
      <Code
        api={api({ sessions: async () => [open], session: async () => open, setLimit })}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    await userEvent.click(await screen.findByRole("button", { name: "$0.21" }));
    const pop = screen.getByRole("dialog", { name: "This session so far" });
    expect(within(pop).getByText("Claude Sonnet 5.5, 14 calls")).toBeTruthy();
    expect(within(pop).getByText("$5.00")).toBeTruthy();
    await userEvent.type(within(pop).getByRole("spinbutton"), "8");
    await userEvent.click(within(pop).getByRole("button", { name: "Change" }));
    expect(setLimit).toHaveBeenCalledWith("s1", 8);
    expect(await within(pop).findByText("$8.00")).toBeTruthy();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "This session so far" })).toBeNull();
  });

  it("follows the address: it opens the session it names and tells the app when another is chosen", async () => {
    const onOpenChange = vi.fn();
    const sessions = async () => [session()];
    const { rerender } = render(
      <Code api={api({ sessions })} {...props} openId={null} onOpenChange={onOpenChange} />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    expect(onOpenChange).toHaveBeenCalledWith("s1");
    expect(screen.queryByRole("textbox", { name: "Ask about this project" })).toBeNull();
    const same = api({ sessions });
    rerender(<Code api={same} {...props} openId="s1" onOpenChange={onOpenChange} />);
    expect(await screen.findByRole("textbox", { name: "Ask about this project" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Projects" }));
    expect(onOpenChange).toHaveBeenLastCalledWith(null);
  });
});

describe("a session that changes files", () => {
  const ASK = {
    ask: "not_undoable",
    step_id: "c1",
    tool: "file_editor",
    command: "str_replace",
    path: ".env",
    says: "The key must be set for the hours to load.",
    project: "bakery-site",
    undo: false,
    steps: 1,
  };
  const edit = {
    event: "tool_call",
    id: "c1",
    name: "file_editor",
    arguments: { command: "str_replace", path: `${FOLDER}/.env` },
  };

  it("shows the agent's question as a card with three answers, and what was answered afterwards", async () => {
    const stream = feed();
    const answer = vi.fn(async () => true);
    const working = session({ mode: "ask", working: true, state: "working" });
    render(
      <Code
        api={api({
          sessions: async () => [working],
          session: async () => working,
          turns: async () => [
            turn({ state: "working", why: "", answer: "", request: "Set the key" }),
          ],
          events: () => stream.events(),
          answer,
        })}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    stream.push(ev({ event: "code_state", state: "working", cost_usd: 0 }));
    stream.push(ev(edit));
    expect(await screen.findByText("Wants to change …/Projects/bakery-site/.env")).toBeTruthy();
    stream.push(ev({ event: "interrupt", interrupt_id: "a1", kind: "code_ask", payload: ASK }));
    const card = await screen.findByRole("region", {
      name: "The agent wants to change a file Undo cannot put back",
    });
    expect(within(card).getByText(".env")).toBeTruthy();
    expect(within(card).getByText(/The key must be set for the hours to load/)).toBeTruthy();
    expect(within(card).getByText(/Ask before changing files Undo cannot put back/)).toBeTruthy();
    // while it waits the bar says so, and nothing else runs
    expect(screen.getByText("Waiting for you")).toBeTruthy();
    expect(screen.getByText(/Nothing else runs until you answer/)).toBeTruthy();
    expect(within(card).getByRole("button", { name: "Yes, change it" })).toBeTruthy();
    expect(within(card).getByRole("button", { name: "No" })).toBeTruthy();
    await userEvent.click(within(card).getByRole("button", { name: "Allow for this project" }));
    expect(answer).toHaveBeenCalledWith("s1", "a1", "allow");
    stream.push(
      ev({
        event: "tool_result",
        id: "c1",
        name: "file_editor",
        status: "ok",
        output: { text: "edited", answer: "allow" },
      }),
    );
    expect(
      await within(card).findByText(
        /You allowed changing files Undo cannot put back for this project\./,
      ),
    ).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "Yes, change it" })).toBeNull();
    expect(await screen.findByText("Changed …/Projects/bakery-site/.env")).toBeTruthy();
    // "Take it back" opens what the project may do
    await userEvent.click(within(card).getByRole("button", { name: "Take it back" }));
    expect(await screen.findByRole("heading", { name: "What bakery-site may do" })).toBeTruthy();
  }, 20_000);

  it("says no, and a card nobody answered is closed when the turn ends", () => {
    const base = [
      ev(edit),
      ev({ event: "interrupt", interrupt_id: "a1", kind: "code_ask", payload: ASK }),
    ];
    const open = buildThread([turn({ state: "working", why: "" })], base)[0];
    expect(open?.parts.at(-1)).toMatchObject({ kind: "ask", id: "a1", open: true, answer: "" });
    const no = buildThread(
      [turn({ state: "working", why: "" })],
      [
        ...base,
        ev({
          event: "tool_result",
          id: "c1",
          name: "file_editor",
          status: "refused",
          output: { text: "no", answer: "no" },
        }),
      ],
    )[0];
    expect(no?.parts.at(-1)).toMatchObject({ kind: "ask", open: false, answer: "no" });
    const steps = no?.parts[0];
    expect(steps?.kind === "steps" && stepLine(steps.steps[0] as never)).toBe(
      "Did not change …/Projects/bakery-site/.env: you said no",
    );
    const stopped = buildThread(
      [turn({ why: "stopped" })],
      [
        ...base,
        ev({ event: "code_state", state: "done", why: "stopped", cost_usd: 0, changed: 0 }),
      ],
    )[0];
    expect(stopped?.parts.at(-1)).toMatchObject({ kind: "ask", open: false, answer: "" });
    // a step that ran with no question because its kind is allowed is marked, never hidden
    const allowed = buildThread(
      [turn()],
      [
        ev(edit),
        ev({
          event: "tool_result",
          id: "c1",
          name: "file_editor",
          status: "ok",
          output: { text: "", answer: "allowed" },
        }),
      ],
    )[0];
    const part = allowed?.parts[0];
    expect(part?.kind === "steps" && part.steps[0]?.answer).toBe("allowed");
    expect(
      stepLine({
        tool: "file_editor",
        given: { command: "create", path: "/p/a.js" },
        status: "ok",
      }),
    ).toBe("Wrote /p/a.js");
    expect(
      stepLine({
        tool: "file_editor",
        given: { command: "insert", path: "/p/a.js" },
        status: "error",
      }),
    ).toBe("Could not change /p/a.js");
  });

  it("says what a turn changed, undoes it and brings it back", async () => {
    const undo = vi.fn(async (_id: string, turnId: string) => ({
      turn_id: turnId,
      undone: true,
      files: 2,
      own_changes: true,
      notes: [],
    }));
    const redo = vi.fn(async (_id: string, turnId: string) => ({
      turn_id: turnId,
      undone: false,
      files: 2,
      own_changes: false,
      notes: [],
    }));
    let undone = false;
    const turns = async () => [
      turn({
        request: "Add the opening hours",
        answer: "Done.",
        changed: 2,
        undone,
        can_undo: !undone,
        can_redo: undone,
      }),
    ];
    const done = session({ mode: "ask", state: "done", turns: 1 });
    render(
      <Code
        api={api({
          sessions: async () => [done],
          session: async () => done,
          turns,
          undo: async (id, turnId) => {
            undone = true;
            return undo(id, turnId);
          },
          redo: async (id, turnId) => {
            undone = false;
            return redo(id, turnId);
          },
          changes: async () => [{ ...CHANGE, undone, can_undo: !undone, can_redo: undone }],
        })}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    const card = await screen.findByRole("region", { name: "What this turn changed" });
    expect(within(card).getByText("Changed 2 files.")).toBeTruthy();
    expect(within(card).getByText(/Not checked/)).toBeTruthy();
    expect(screen.getByText("Ask me", { selector: "output" })).toBeTruthy();
    await userEvent.click(within(card).getByRole("button", { name: "Undo this turn" }));
    expect(undo).toHaveBeenCalledWith("s1", "t1");
    const gone = await screen.findByRole("region", { name: "An undone turn" });
    expect(within(gone).getByText("You undid this turn.")).toBeTruthy();
    expect(within(gone).getByText(/2 files are back to how they were before it/)).toBeTruthy();
    await userEvent.click(within(gone).getByRole("button", { name: "Bring it back" }));
    expect(redo).toHaveBeenCalledWith("s1", "t1");
    expect(await screen.findByRole("region", { name: "What this turn changed" })).toBeTruthy();
  }, 20_000);

  it("lists a turn's files in the Changes tab, shows one before and after, and undoes from there", async () => {
    const undo = vi.fn(async (_id: string, turnId: string) => ({
      turn_id: turnId,
      undone: true,
      files: 2,
      own_changes: true,
      notes: [],
    }));
    const change = vi.fn(async () => CHANGED_FILE);
    let undone = false;
    const done = session({ mode: "ask", state: "done", turns: 1 });
    render(
      <Code
        api={api({
          sessions: async () => [done],
          session: async () => done,
          turns: async () => [turn({ changed: 2, undone, can_undo: !undone, can_redo: undone })],
          changes: async () => [{ ...CHANGE, undone, can_undo: !undone, can_redo: undone }],
          change,
          undo: async (id, turnId) => {
            undone = true;
            return undo(id, turnId);
          },
        })}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    const tabs = await screen.findByRole("tablist", { name: "Beside the chat" });
    await userEvent.click(within(tabs).getByRole("tab", { name: "Changes" }));
    const pane = await screen.findByRole("region", { name: "Changes" });
    const list = await within(pane).findByRole("navigation", { name: "Files turn 1 changed" });
    expect(within(list).getByRole("button", { name: /home\.html/ })).toBeTruthy();
    expect(within(list).getByText("test")).toBeTruthy(); // a test file is marked
    await waitFor(() => expect(change).toHaveBeenCalledWith("s1", "t1", "src/home.html"));
    const shown = await within(pane).findByLabelText("src/home.html, before and after");
    expect(shown.querySelectorAll('[data-line="del"]').length).toBe(1);
    expect(shown.querySelectorAll('[data-line="add"]').length).toBe(1);
    expect(within(shown).getByText("<p>Welcome</p>")).toBeTruthy();
    await userEvent.click(within(pane).getByRole("radio", { name: "After" }));
    const after = await within(pane).findByLabelText("src/home.html, after");
    expect(within(after).queryByText("<p>Welcome</p>")).toBeNull();
    expect(within(after).getByText("<p>Open 9 to 5</p>")).toBeTruthy();
    expect(within(pane).getByText(/It does not put back files your project ignores/)).toBeTruthy();
    await userEvent.click(within(pane).getByRole("button", { name: "Undo this turn" }));
    expect(undo).toHaveBeenCalledWith("s1", "t1");
    expect(await within(pane).findByText("Turn 1 is undone")).toBeTruthy();
    // the person's own changes went back too, and the screen says so
    expect(
      await within(pane).findByText(/Files you changed yourself after this turn went back too/),
    ).toBeTruthy();
    expect(within(pane).getByRole("button", { name: "Bring it back" })).toBeTruthy();
  }, 20_000);

  it("says so when nothing was changed yet", async () => {
    const quiet = session({ mode: "ask" });
    render(
      <Code api={api({ sessions: async () => [quiet], session: async () => quiet })} {...props} />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    const tabs = await screen.findByRole("tablist", { name: "Beside the chat" });
    await userEvent.click(within(tabs).getByRole("tab", { name: "Changes" }));
    expect(await screen.findByText("No changes yet")).toBeTruthy();
  });

  it("changes the mode from the pill, and allows a kind in what the project may do", async () => {
    const setMode = vi.fn(async (_id: string, mode: CodeSession["mode"]) => session({ mode }));
    const allow = vi.fn(async (_id: string, kind: string, allowed: boolean) => ({
      ...PROJECT,
      kinds: PROJECT.kinds.map((k) => (k.id === kind ? { ...k, allowed } : k)),
    }));
    const asking = session({ mode: "ask" });
    render(
      <Code
        api={api({ sessions: async () => [asking], session: async () => asking, setMode, allow })}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    await userEvent.click(
      await screen.findByRole("button", { name: "How much the agent asks: Ask me" }),
    );
    const menu = screen.getByRole("menu", { name: "How much the agent asks" });
    expect(
      within(menu)
        .getByRole("menuitemradio", { name: /Ask me/ })
        .getAttribute("aria-checked"),
    ).toBe("true");
    expect(within(menu).getByText(/Reads the project and writes a plan/)).toBeTruthy();
    await userEvent.click(within(menu).getByRole("menuitemradio", { name: /Work on its own/ }));
    expect(setMode).toHaveBeenCalledWith("s1", "own");
    expect(
      await screen.findByRole("button", { name: "How much the agent asks: Work on its own" }),
    ).toBeTruthy();
    await userEvent.click(
      screen.getByRole("button", { name: "How much the agent asks: Work on its own" }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: /What this project may do/ }));
    expect(await screen.findByRole("heading", { name: "What bakery-site may do" })).toBeTruthy();
    expect(
      screen.getByText(/once the agent can run commands/, { selector: "li:nth-child(2) *" }),
    ).toBeTruthy();
    await userEvent.click(
      screen.getByRole("button", { name: "Allow: changing files Undo cannot put back" }),
    );
    expect(allow).toHaveBeenCalledWith("s1", "not_undoable", true);
    expect(
      await screen.findByRole("button", { name: "Remove: changing files Undo cannot put back" }),
    ).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("heading", { name: "What bakery-site may do" })).toBeNull();
  }, 20_000);

  it("carries out a plan: the session leaves Plan and the agent is told to go on", async () => {
    const setMode = vi.fn(async (_id: string, mode: CodeSession["mode"]) =>
      session({ mode, turns: 1, state: "done" }),
    );
    const send = vi.fn(async () => session({ mode: "ask", working: true, state: "working" }));
    const planned = session({ mode: "plan", turns: 1, state: "done" });
    render(
      <Code
        api={api({
          sessions: async () => [planned],
          session: async () => planned,
          turns: async () => [turn()],
          setMode,
          send,
        })}
        {...props}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: /^bakery-site/ }));
    const plan = await screen.findByRole("region", { name: "A plan" });
    expect(within(plan).getByText(/switches this session to “Ask me”/)).toBeTruthy();
    await userEvent.click(within(plan).getByRole("button", { name: "Carry out this plan" }));
    expect(setMode).toHaveBeenCalledWith("s1", "ask");
    await waitFor(() => expect(send).toHaveBeenCalledWith("s1", CARRY_OUT));
  });

  it("says who waits on the list of projects", async () => {
    const sessions = async () => [session({ title: "Set the key", working: true, waiting: true })];
    render(<Code api={api({ sessions })} {...props} />);
    expect(await screen.findByText("Waiting for you")).toBeTruthy();
  });
});
