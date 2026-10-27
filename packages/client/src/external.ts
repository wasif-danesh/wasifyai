// Settings > Other apps > "Tools from other apps" (ADR-0070): the outside MCP servers the person
// added, their tools, and what each one did.
import type { Transport } from "./transport";
import { HttpError } from "./transport";

export type ExternalTool = {
  server: string;
  name: string;
  description: string;
  annotations: Record<string, unknown>;
  input_schema: Record<string, unknown>;
};

export type ExternalServer = {
  id: string;
  name: string;
  transport: "http" | "stdio";
  url: string;
  command: string;
  args: string[];
  host: string;
  env_names: string[];
  has_token: boolean;
  trust: "ask" | "blocked";
  allowed_tools: string[];
  timeout_s: number;
  keep_content: boolean;
  created_at: string;
  last_used_at: string | null;
  calls: number;
  bytes_sent: number;
  bytes_received: number;
  failures: number;
  unhealthy: boolean;
  last_error: string;
  /** The tools listed at the last Test (or call) of this session; null before one. */
  tools: ExternalTool[] | null;
};

export type ExternalServerIn = {
  name: string;
  transport: "http" | "stdio";
  url?: string;
  command?: string;
  args?: string[] | string;
  env?: Record<string, string>;
  token?: string;
  trust?: "ask" | "blocked";
  allowed_tools?: string[] | string;
  timeout_s?: number;
  /** stdio: the name typed again (adding a program is installing software). */
  confirm_name?: string;
};

export type ExternalServerPatch = Partial<
  Pick<ExternalServerIn, "name" | "url" | "command" | "args" | "env" | "token" | "trust"> & {
    allowed_tools: string[] | string;
    timeout_s: number;
    keep_content: boolean;
  }
>;

export type ExternalTest = {
  ok: boolean;
  error: string;
  tools: ExternalTool[];
  ms?: number;
  server: ExternalServer;
};

export type ExternalActivity = {
  id: string;
  tool: string;
  status: string;
  duration_ms: number;
  bytes_sent: number;
  bytes_received: number;
  content: string;
  created_at: string;
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

export function createExternalApi(transport: Transport) {
  return {
    list: () => json<{ servers: ExternalServer[] }>(transport, "/external"),
    add: (body: ExternalServerIn) =>
      json<{ server: ExternalServer }>(transport, "/external", {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      }),
    update: (id: string, body: ExternalServerPatch) =>
      json<{ server: ExternalServer }>(transport, `/external/${id}`, {
        method: "PATCH",
        headers,
        body: JSON.stringify(body),
      }),
    remove: (id: string) =>
      json<{ removed: string }>(transport, `/external/${id}`, { method: "DELETE" }),
    test: (id: string) => json<ExternalTest>(transport, `/external/${id}/test`, { method: "POST" }),
    activity: (id: string) =>
      json<{ activity: ExternalActivity[] }>(transport, `/external/${id}/activity`),
  };
}

export type ExternalApi = ReturnType<typeof createExternalApi>;
