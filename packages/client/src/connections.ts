// Settings > Connections and the cards an agent waits for (ADR-0069): the engine's `/connections`
// routes, the pending approvals, and the window's event stream.
import type { Transport } from "./transport";
import { HttpError } from "./transport";

export type Connection = {
  id: string;
  name: string;
  kind: "client" | "launcher";
  scopes: string[];
  approval: Record<string, string>;
  read_folders: string[];
  write_folders: string[];
  rate_per_minute: number;
  calls_per_day: number;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
};

export type ActivityEntry = {
  method: string;
  tool: string;
  status: string;
  duration_ms: number;
  bytes: number;
  created_at: string;
};

export type Snippets = {
  launcher: string;
  snippets: Record<string, string>;
};

export type LauncherState = {
  available: boolean;
  enabled: boolean;
  connection?: Connection | null;
  file?: string;
};

export type RunningJob = {
  job_id: string;
  action_id: string;
  origin: string;
  /** The connection's name when an agent started it ("Codex"); null for the window or the assistant. */
  from: string | null;
  seconds: number;
  cancellable: boolean;
};

export type FixedPortState = {
  available: boolean;
  port: number | null;
  url: string | null;
};

export type PendingApproval = {
  approval_id: string;
  connection: string;
  action_id: string;
  title: string;
  summary: string;
  params: Record<string, string | number | boolean>;
};

export type ApprovalEvent = {
  kind: "approval";
  approval_id: string;
  connection: string;
  action_id: string;
  title: string;
  summary: string;
};

/** An outside server asks the person something mid-call (ADR-0070 decision 10): a form card. */
export type ElicitationEvent = {
  kind: "elicitation";
  form_id: string;
  server: string;
  message: string;
};

export type WindowEvent = ApprovalEvent | ElicitationEvent;

async function json<T>(transport: Transport, path: string, init?: RequestInit): Promise<T> {
  const res = await transport.fetch(path, init);
  if (!res.ok) {
    let detail = `The engine answered ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // not JSON
    }
    throw new HttpError(res.status, detail);
  }
  return (await res.json()) as T;
}

const headers = { "content-type": "application/json" };

export function createConnectionsApi(transport: Transport) {
  return {
    list: () => json<{ connections: Connection[] }>(transport, "/connections"),
    create: (body: { name: string; scopes?: string[]; approval?: Record<string, string> }) =>
      json<{ connection: Connection; secret: string }>(transport, "/connections", {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      }),
    update: (
      id: string,
      body: Partial<
        Pick<
          Connection,
          | "name"
          | "scopes"
          | "approval"
          | "read_folders"
          | "write_folders"
          | "rate_per_minute"
          | "calls_per_day"
        >
      >,
    ) =>
      json<Connection>(transport, `/connections/${id}`, {
        method: "PATCH",
        headers,
        body: JSON.stringify(body),
      }),
    rotate: (id: string) =>
      json<{ connection: Connection; secret: string }>(transport, `/connections/${id}/rotate`, {
        method: "POST",
      }),
    revoke: (id: string) => json<Connection>(transport, `/connections/${id}`, { method: "DELETE" }),
    activity: (id: string) =>
      json<{ activity: ActivityEntry[] }>(transport, `/connections/${id}/activity`),
    snippets: () => json<Snippets>(transport, "/connections/snippets"),
    launcher: () => json<LauncherState>(transport, "/connections/launcher"),
    setLauncher: (enabled: boolean) =>
      json<LauncherState>(transport, "/connections/launcher", {
        method: "PUT",
        headers,
        body: JSON.stringify({ enabled }),
      }),
    /** A SKILL.md for Claude Code, generated from the catalogue (stage M3). */
    skill: async (): Promise<string> => {
      const res = await transport.fetch("/connections/skill");
      if (!res.ok) throw new HttpError(res.status, "no skill file");
      return await res.text();
    },
    fixedPort: () => json<FixedPortState>(transport, "/connections/fixed-port"),
    /** A port turns the HTTP option on; null turns it off. */
    setFixedPort: (port: number | null) =>
      json<FixedPortState>(transport, "/connections/fixed-port", {
        method: "PUT",
        headers,
        body: JSON.stringify({ port }),
      }),
    /** The jobs running for this person, with who started each ("from Codex"). */
    jobs: () => json<{ jobs: RunningJob[] }>(transport, "/actions/jobs"),
    cancelJob: (jobId: string) =>
      json<{ job_id: string; status: string; stopped: boolean }>(
        transport,
        `/actions/jobs/${jobId}/cancel`,
        { method: "POST" },
      ),
    pendingApprovals: () => json<{ approvals: PendingApproval[] }>(transport, "/actions/approvals"),
    decide: (approvalId: string, approved: boolean) =>
      json<{ approval_id: string; status: string }>(transport, `/actions/approvals/${approvalId}`, {
        method: "POST",
        headers,
        body: JSON.stringify({ approved }),
      }),
    /** The window's event stream: `approval` events while an agent waits, `elicitation` events while an outside
     * server waits for an answer. Ends when `signal` aborts. */
    async events(onEvent: (event: WindowEvent) => void, signal: AbortSignal): Promise<void> {
      const res = await transport.fetch("/desktop/events", { signal });
      if (!res.ok || !res.body) throw new HttpError(res.status, "no event stream");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) return;
        buf += decoder.decode(value, { stream: true });
        let idx = buf.indexOf("\n\n");
        while (idx !== -1) {
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          idx = buf.indexOf("\n\n");
          const data = block
            .split("\n")
            .filter((l) => l.startsWith("data:"))
            .map((l) => l.slice(5).trim())
            .join("\n");
          if (!data) continue;
          try {
            const parsed = JSON.parse(data) as WindowEvent;
            if (parsed && (parsed.kind === "approval" || parsed.kind === "elicitation"))
              onEvent(parsed);
          } catch {
            // not ours
          }
        }
      }
    },
  };
}

export type ConnectionsApi = ReturnType<typeof createConnectionsApi>;
