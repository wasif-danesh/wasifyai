// @vitest-environment jsdom
// Settings > Connections and the approval cards (ADR-0069 decisions 3 and 8), on a scripted engine.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ApprovalEvent, Connection, ConnectionsApi, PendingApproval } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { ApprovalCards } from "./ApprovalCards";
import { ConnectionsSettings } from "./ConnectionsSettings";

const codex: Connection = {
  id: "c1",
  name: "Codex",
  kind: "client",
  scopes: ["make", "models", "read"],
  approval: {},
  read_folders: [],
  write_folders: [],
  rate_per_minute: 60,
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
