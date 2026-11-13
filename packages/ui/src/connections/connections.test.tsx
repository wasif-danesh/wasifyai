// @vitest-environment jsdom
// Settings > Connections and the approval cards (ADR-0069 decisions 3 and 8), on a scripted engine.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  ApprovalEvent,
  Connection,
  ConnectionsApi,
  ExternalApi,
  ExternalServer,
  ImportDefinition,
  PendingApproval,
  PendingForm,
} from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { ApprovalCards } from "./ApprovalCards";
import { ConnectionsSettings } from "./ConnectionsSettings";
import { ElicitationCards, FormCard, fieldsOf } from "./ElicitationCards";
import { ExternalServers } from "./ExternalServers";

const codex: Connection = {
  id: "c1",
  name: "Codex",
  kind: "client",
  scopes: ["make", "models", "read"],
  approval: {},
  read_folders: [],
  write_folders: [],
  rate_per_minute: 60,
  calls_per_day: 1000,
  created_at: "2026-10-27T00:00:00Z",
  last_used_at: null,
  revoked: false,
};

function api(over: Partial<ConnectionsApi> = {}): ConnectionsApi {
  return {
    list: vi.fn(async () => ({ connections: [codex] })),
    create: vi.fn(async ({ name }) => ({
      connection: { ...codex, id: "c2", name },
      secret: "wsc_c2_abcdefghijklmnopqrstuvwxyz",
    })),
    update: vi.fn(async (id, body) => ({ ...codex, id, ...body }) as Connection),
    rotate: vi.fn(async () => ({ connection: codex, secret: "wsc_c1_new" })),
    revoke: vi.fn(async () => ({ ...codex, revoked: true })),
    activity: vi.fn(async () => ({ activity: [] })),
    snippets: vi.fn(async () => ({
      launcher: "/Applications/Wasify AI.app/Contents/MacOS/wasify-mcp",
      snippets: {
        claude_code_command:
          'claude mcp add --transport stdio wasify -- "/Applications/Wasify AI.app/Contents/MacOS/wasify-mcp"',
        codex_toml:
          '[mcp_servers.wasify]\ncommand = "/Applications/Wasify AI.app/Contents/MacOS/wasify-mcp"\n',
        opencode_json: '{"mcp": {"wasify": {"type": "local"}}}',
      },
    })),
    launcher: vi.fn(async () => ({ available: true, enabled: false })),
    skill: vi.fn(async () => "---\nname: wasify-ai\n---\n\n# Wasify AI\n"),
    fixedPort: vi.fn(async () => ({ available: true, port: null, url: null })),
    setFixedPort: vi.fn(async (port) => ({
      available: true,
      port,
      url: port ? `http://127.0.0.1:${port}/mcp` : null,
    })),
    jobs: vi.fn(async () => ({ jobs: [] })),
    cancelJob: vi.fn(async (job_id) => ({ job_id, status: "cancelled", stopped: true })),
    setLauncher: vi.fn(async (enabled) => ({ available: true, enabled })),
    pendingApprovals: vi.fn(async () => ({ approvals: [] })),
    decide: vi.fn(async (approval_id) => ({ approval_id, status: "approved" })),
    events: vi.fn(async (_on, signal) => {
      await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve()));
    }),
    ...over,
  };
}

describe("Settings > Connections", () => {
  it("switches the launcher on and then shows the command for each client", async () => {
    const a = api();
    const user = userEvent.setup();
    render(<ConnectionsSettings api={a} />);
    const box = await screen.findByRole("checkbox", { name: /let other apps use wasify ai/i });
    expect(box).not.toBeChecked();
    expect(screen.queryByText(/claude mcp add/)).toBeNull();
    await user.click(box);
    await waitFor(() => expect(a.setLauncher).toHaveBeenCalledWith(true));
    expect(await screen.findByText(/claude mcp add/)).toBeInTheDocument();
    expect(screen.getByText(/mcp_servers.wasify/)).toBeInTheDocument();
  });

  it("lists a connection with its scopes in words, and a change goes to the engine", async () => {
    const a = api();
    const user = userEvent.setup();
    render(<ConnectionsSettings api={a} />);
    expect(await screen.findByText("Codex")).toBeInTheDocument();
    const library = screen.getByRole("checkbox", { name: /see and change your creations/i });
    expect(library).not.toBeChecked();
    await user.click(library);
    await waitFor(() =>
      expect(a.update).toHaveBeenCalledWith("c1", {
        scopes: ["make", "models", "read", "library"],
      }),
    );
    await user.selectOptions(screen.getByRole("combobox"), "auto");
    await waitFor(() =>
      expect(a.update).toHaveBeenCalledWith("c1", { approval: { make: "auto" } }),
    );
  });

  it("saves the daily quota of a connection", async () => {
    const a = api();
    const user = userEvent.setup();
    render(<ConnectionsSettings api={a} />);
    const quota = await screen.findByLabelText(/tool calls a day/i);
    expect(quota).toHaveValue(1000);
    await user.clear(quota);
    await user.type(quota, "50{Enter}");
    await waitFor(() => expect(a.update).toHaveBeenCalledWith("c1", { calls_per_day: 50 }));
  });

  it("shows what runs now, who started it, and Stop ends it", async () => {
    const a = api({
      jobs: vi.fn(async () => ({
        jobs: [
          {
            job_id: "j1",
            action_id: "image.generate",
            origin: "mcp:Codex",
            from: "Codex",
            seconds: 12,
            cancellable: true,
          },
        ],
      })),
    });
    const user = userEvent.setup();
    render(<ConnectionsSettings api={a} />);
    expect(await screen.findByText("image.generate from Codex")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(a.cancelJob).toHaveBeenCalledWith("j1"));
    expect(screen.queryByText("image.generate from Codex")).toBeNull();
  });

  it("turns the fixed port on once the launcher is on, and the HTTP command follows", async () => {
    const a = api({
      launcher: vi.fn(async () => ({ available: true, enabled: true })),
      snippets: vi
        .fn()
        .mockResolvedValueOnce({
          launcher: "/x/wasify-mcp",
          snippets: { claude_code_command: "a" },
        })
        .mockResolvedValue({
          launcher: "/x/wasify-mcp",
          snippets: {
            claude_code_command: "a",
            claude_code_http: "claude mcp add --transport http wasify http://127.0.0.1:8765/mcp",
          },
        }),
    });
    const user = userEvent.setup();
    render(<ConnectionsSettings api={a} />);
    await user.type(await screen.findByLabelText("Port"), "8765");
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(a.setFixedPort).toHaveBeenCalledWith(8765));
    expect(await screen.findByText("http://127.0.0.1:8765/mcp")).toBeInTheDocument();
    expect(await screen.findByText(/--transport http/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show the skill file" }));
    expect(await screen.findByText(/name: wasify-ai/)).toBeInTheDocument();
  });

  it("adds a connection and shows its secret once", async () => {
    const a = api();
    const user = userEvent.setup();
    render(<ConnectionsSettings api={a} />);
    await user.type(await screen.findByLabelText("New connection"), "Claude Code at work");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByText("wsc_c2_abcdefghijklmnopqrstuvwxyz")).toBeInTheDocument();
    expect(a.create).toHaveBeenCalledWith({ name: "Claude Code at work" });
    await user.click(screen.getByRole("button", { name: /i have copied it/i }));
    expect(screen.queryByText("wsc_c2_abcdefghijklmnopqrstuvwxyz")).toBeNull();
    expect(screen.getByText("Claude Code at work")).toBeInTheDocument();
  });
});

describe("the approval cards", () => {
  const waiting: PendingApproval = {
    approval_id: "ap1",
    connection: "Codex",
    action_id: "music.generate",
    title: "Make music",
    summary: "Make a 30 second song",
    params: { description: "upbeat pop", seconds: 30 },
  };

  it("shows what an agent wants, from the pending list and from an event, and Allow answers it", async () => {
    const got: { on?: (e: ApprovalEvent) => void } = {};
    const pending = vi
      .fn()
      .mockResolvedValueOnce({ approvals: [] })
      .mockResolvedValue({ approvals: [waiting] });
    const a = api({
      pendingApprovals: pending,
      events: vi.fn(async (on, signal) => {
        got.on = on;
        await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve()));
      }),
    });
    const user = userEvent.setup();
    render(<ApprovalCards api={a} />);
    await waitFor(() => expect(got.on).toBeDefined());
    expect(screen.queryByText(/Codex wants to/)).toBeNull();
    got.on?.({
      kind: "approval",
      approval_id: "ap1",
      connection: "Codex",
      action_id: "music.generate",
      title: "Make music",
      summary: "",
    });
    const card = await screen.findByRole("region", { name: "Codex wants to: Make music" });
    expect(card).toHaveTextContent("upbeat pop");
    await user.click(screen.getByRole("button", { name: "Allow once" }));
    await waitFor(() => expect(a.decide).toHaveBeenCalledWith("ap1", true));
  });

  it("Deny says no", async () => {
    const a = api({ pendingApprovals: vi.fn(async () => ({ approvals: [waiting] })) });
    const user = userEvent.setup();
    render(<ApprovalCards api={a} />);
    await user.click(await screen.findByRole("button", { name: "Deny" }));
    await waitFor(() => expect(a.decide).toHaveBeenCalledWith("ap1", false));
  });
});

const github: ExternalServer = {
  id: "s1",
  name: "github",
  transport: "http",
  url: "https://mcp.github.example/mcp",
  command: "",
  args: [],
  host: "mcp.github.example",
  env_names: [],
  has_token: true,
  trust: "ask",
  allowed_tools: [],
  timeout_s: 60,
  keep_content: false,
  created_at: "2026-10-27T00:00:00Z",
  last_used_at: null,
  calls: 3,
  bytes_sent: 2048,
  bytes_received: 40960,
  failures: 0,
  unhealthy: false,
  last_error: "",
  tools: null,
};

function externalApiWith(over: Partial<ExternalApi> = {}): ExternalApi {
  return {
    list: vi.fn(async () => ({ servers: [github] })),
    add: vi.fn(async (body) => ({
      server: { ...github, id: "s2", name: body.name, transport: body.transport },
    })),
    update: vi.fn(async (id, body) => ({ server: { ...github, id, ...body } as ExternalServer })),
    remove: vi.fn(async (id) => ({ removed: id })),
    test: vi.fn(async () => ({
      ok: true,
      error: "",
      ms: 12,
      tools: [],
      server: {
        ...github,
        tools: [
          {
            server: "github",
            name: "search_issues",
            description: "Search issues",
            annotations: { readOnlyHint: true },
            input_schema: {},
          },
        ],
      },
    })),
    activity: vi.fn(async () => ({ activity: [] })),
    log: vi.fn(async () => ({ log: "server started" })),
    resources: vi.fn(async () => ({ resources: [] })),
    attachResource: vi.fn(async () => ({
      id: "u1",
      kind: "document" as const,
      name: "github: plan",
      chars: 20,
      truncated: false,
    })),
    prompts: vi.fn(async () => ({ prompts: [] })),
    promptText: vi.fn(async () => ({ text: "" })),
    forms: vi.fn(async () => ({ forms: [] })),
    answerForm: vi.fn(async (form_id, action) => ({ form_id, action })),
    importFind: vi.fn(async () => ({ found: [] })),
    importAdd: vi.fn(async (_where, name) => ({ server: { ...github, id: "s9", name } })),
    ...over,
  };
}
describe("Tools from other apps (ADR-0070)", () => {
  it("shows a server with what it talks to and what it sent, and Test lists its tools", async () => {
    const a = externalApiWith();
    const user = userEvent.setup();
    render(<ExternalServers api={a} />);
    expect(await screen.findByText("github")).toBeInTheDocument();
    expect(screen.getByText(/talks to mcp.github.example/)).toBeInTheDocument();
    expect(screen.getByText(/3 calls, 2 KB sent, 40 KB received/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByText("search_issues")).toBeInTheDocument();
    expect(screen.getByText(/says it only reads/)).toBeInTheDocument();
    const trust = screen.getByRole("combobox", { name: /this server/i });
    expect(screen.getByText(/runs the tools it says only read/)).toBeInTheDocument();
    await user.selectOptions(trust, "trusted_read_only");
    await waitFor(() =>
      expect(a.update).toHaveBeenCalledWith("s1", { trust: "trusted_read_only" }),
    );
  });

  it("adds a program only once its name is typed again, with its variables", async () => {
    const a = externalApiWith();
    const user = userEvent.setup();
    render(<ExternalServers api={a} />);
    await user.type(await screen.findByLabelText("Add a server"), "files");
    await user.selectOptions(screen.getByLabelText("Kind"), "stdio");
    await user.type(screen.getByLabelText(/command, with its arguments/i), "npx -y server-fs /tmp");
    await user.type(screen.getByLabelText(/variables it needs/i), "API_KEY=abc");
    const add = screen.getByRole("button", { name: "Add" });
    expect(add).toBeDisabled();
    expect(screen.getByText(/installing software/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/type the name to confirm/i), "files");
    await user.click(add);
    await waitFor(() =>
      expect(a.add).toHaveBeenCalledWith({
        name: "files",
        transport: "stdio",
        command: "npx",
        args: ["-y", "server-fs", "/tmp"],
        env: { API_KEY: "abc" },
        confirm_name: "files",
      }),
    );
    expect(await screen.findByText("files")).toBeInTheDocument();
  });

  it("Remove asks first and then deletes the server", async () => {
    const a = externalApiWith();
    const user = userEvent.setup();
    render(<ExternalServers api={a} />);
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    expect(screen.getByText(/token or variables are deleted/i)).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "Remove" });
    await user.click(buttons[buttons.length - 1] as HTMLElement);
    await waitFor(() => expect(a.remove).toHaveBeenCalledWith("s1"));
    await waitFor(() => expect(screen.queryByText("github")).toBeNull());
  });
});

describe("a server's question as a form (ADR-0070 decision 10)", () => {
  const form: PendingForm = {
    form_id: "f1",
    server: "github",
    message: "What is your name?",
    schema: {
      type: "object",
      properties: {
        name: { type: "string", description: "What to call you" },
        age: { type: "integer" },
        formal: { type: "boolean" },
        tone: { type: "string", enum: ["warm", "plain"] },
      },
      required: ["name"],
    },
    created_at: "2026-10-27T00:00:00Z",
  };

  it("draws the fields from the schema", () => {
    const fields = fieldsOf(form.schema);
    expect(fields.map((f) => [f.name, f.kind, f.required])).toEqual([
      ["name", "text", true],
      ["age", "number", false],
      ["formal", "bool", false],
      ["tone", "choice", false],
    ]);
  });

  it("sends the typed values, as numbers and booleans where the schema says", async () => {
    const onAnswer = vi.fn();
    const user = userEvent.setup();
    render(<FormCard form={form} onAnswer={onAnswer} />);
    expect(screen.getByText("github asks")).toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText(/^name/), "Ada");
    await user.type(screen.getByLabelText(/^age/), "36");
    await user.click(screen.getByLabelText(/^formal/));
    await user.selectOptions(screen.getByLabelText(/^tone/), "warm");
    await user.click(send);
    expect(onAnswer).toHaveBeenCalledWith("accept", {
      name: "Ada",
      age: 36,
      formal: true,
      tone: "warm",
    });
    await user.click(screen.getByRole("button", { name: "Decline" }));
    expect(onAnswer).toHaveBeenLastCalledWith("decline");
  });

  it("shows a form from the pending list after an event, and the answer goes to the engine", async () => {
    const got: { on?: (e: ApprovalEvent | { kind: "elicitation" }) => void } = {};
    const pending = vi
      .fn()
      .mockResolvedValueOnce({ forms: [] })
      .mockResolvedValue({ forms: [form] });
    const connections = api({
      events: vi.fn(async (on, signal) => {
        got.on = on;
        await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve()));
      }),
    });
    const external = externalApiWith({ forms: pending });
    const user = userEvent.setup();
    render(<ElicitationCards external={external} connections={connections} />);
    await waitFor(() => expect(got.on).toBeDefined());
    expect(screen.queryByText("github asks")).toBeNull();
    got.on?.({ kind: "elicitation", form_id: "f1", server: "github", message: "x" } as never);
    expect(await screen.findByText("github asks")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^name/), "Ada");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(external.answerForm).toHaveBeenCalledWith("f1", "accept", {
        name: "Ada",
        formal: false,
      }),
    );
  });

  it("imports a definition from another client's config on a click", async () => {
    const found: ImportDefinition[] = [
      {
        source: "codex",
        name: "jira",
        transport: "stdio",
        command: "jira-mcp",
        args: [],
        url: "",
        env_names: ["JIRA_TOKEN"],
        has_token: false,
        note: "",
      },
      {
        source: "codex",
        name: "old",
        transport: "http",
        command: "",
        args: [],
        url: "https://old.example/sse",
        env_names: [],
        has_token: false,
        note: "sse is not supported",
      },
    ];
    const external = externalApiWith({
      importFind: vi.fn(async () => ({
        found,
      })),
    });
    const user = userEvent.setup();
    render(<ExternalServers api={external} />);
    await user.selectOptions(await screen.findByLabelText("From"), "codex");
    await user.click(screen.getByRole("button", { name: "Find servers" }));
    expect(await screen.findByText("jira")).toBeInTheDocument();
    expect(screen.getByText(/with JIRA_TOKEN/)).toBeInTheDocument();
    expect(screen.getByText(/sse is not supported/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Add" })).toHaveLength(2); // the form's Add and jira's
    await user.click(screen.getAllByRole("button", { name: "Add" })[1] as HTMLElement);
    await waitFor(() =>
      expect(external.importAdd).toHaveBeenCalledWith({ source: "codex" }, "jira"),
    );
    expect(await screen.findByText("added")).toBeInTheDocument();
  });
});
