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
  trust: "ask" | "trusted_read_only" | "blocked";
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
  trust?: "ask" | "trusted_read_only" | "blocked";
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

/** Something a server offers to read (ADR-0070 decision 10): the person attaches it to a message. */
export type ExternalResource = {
  server: string;
  uri: string;
  name: string;
  description: string;
  mime_type: string;
};

/** A prompt a server offers: a template for the box, with its arguments. */
export type ExternalPrompt = {
  server: string;
  name: string;
  title: string;
  description: string;
  arguments: { name: string; description: string; required: boolean }[];
};

/** A question an outside server is waiting on, shown as a form in the window. */
export type PendingForm = {
  form_id: string;
  server: string;
  message: string;
  /** a JSON schema of top-level fields: string, number, integer, boolean, enum */
  schema: Record<string, unknown>;
  created_at: string;
};

export type FormAction = "accept" | "decline" | "cancel";

/** A server definition found in another client's config (values stay on the engine). */
export type ImportDefinition = {
  source: string;
  name: string;
  transport: "http" | "stdio";
  command: string;
  args: string[];
  url: string;
  env_names: string[];
  has_token: boolean;
  /** why it cannot be added as it is */
  note: string;
};

export type ImportSource = "claude_code" | "claude_desktop" | "codex";

export type ImportWhere = { source: ImportSource; path?: string; folder?: string };

export type AttachedResource = {
  id: string;
  kind: "document";
  name: string;
  chars: number;
  truncated: boolean;
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
    /** The last part of a program's output (stdio servers). */
    log: (id: string) => json<{ log: string }>(transport, `/external/${id}/log`),
    activity: (id: string) =>
      json<{ activity: ExternalActivity[] }>(transport, `/external/${id}/activity`),
    resources: (id: string) =>
      json<{ resources: ExternalResource[] }>(transport, `/external/${id}/resources`),
    /** Read a text resource and keep it as a document the next message can attach. */
    attachResource: (id: string, uri: string) =>
      json<AttachedResource>(transport, `/external/${id}/resources/attach`, {
        method: "POST",
        headers,
        body: JSON.stringify({ uri }),
      }),
    prompts: (id: string) =>
      json<{ prompts: ExternalPrompt[] }>(transport, `/external/${id}/prompts`),
    promptText: (id: string, name: string, args: Record<string, string>) =>
      json<{ text: string }>(transport, `/external/${id}/prompts/get`, {
        method: "POST",
        headers,
        body: JSON.stringify({ name, arguments: args }),
      }),
    forms: () => json<{ forms: PendingForm[] }>(transport, "/external/forms"),
    answerForm: (formId: string, action: FormAction, content?: Record<string, unknown>) =>
      json<{ form_id: string; action: string }>(transport, `/external/forms/${formId}`, {
        method: "POST",
        headers,
        body: JSON.stringify({ action, content: content ?? null }),
      }),
    /** The definitions another client's config holds; nothing is added yet. */
    importFind: (where: ImportWhere) =>
      json<{ found: ImportDefinition[] }>(transport, "/external/import", {
        method: "POST",
        headers,
        body: JSON.stringify(where),
      }),
    /** Add one of them, as the file has it (its variables go to the keychain on the engine). */
    importAdd: (where: ImportWhere, name: string) =>
      json<{ server: ExternalServer }>(transport, "/external/import/add", {
        method: "POST",
        headers,
        body: JSON.stringify({ ...where, name }),
      }),
  };
}

export type ExternalApi = ReturnType<typeof createExternalApi>;
