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
    update: (id: string, body: Partial<Pick<Connection, "name" | "scopes" | "approval">>) =>
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
    pendingApprovals: () => json<{ approvals: PendingApproval[] }>(transport, "/actions/approvals"),
    decide: (approvalId: string, approved: boolean) =>
      json<{ approval_id: string; status: string }>(transport, `/actions/approvals/${approvalId}`, {
        method: "POST",
        headers,
        body: JSON.stringify({ approved }),
      }),
    /** The window's event stream: `approval` events while an agent waits. Ends when `signal` aborts. */
    async events(onEvent: (event: ApprovalEvent) => void, signal: AbortSignal): Promise<void> {
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
            const parsed = JSON.parse(data) as ApprovalEvent;
            if (parsed && parsed.kind === "approval") onEvent(parsed);
          } catch {
            // not ours
          }
        }
      }
    },
  };
}

export type ConnectionsApi = ReturnType<typeof createConnectionsApi>;
