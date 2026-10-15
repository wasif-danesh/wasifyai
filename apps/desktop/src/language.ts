// SPDX-License-Identifier: AGPL-3.0-only
// The engine's chat-model routes (`/desktop/language`, services/api/src/wasifyai_api/desktop_llm.py):
// which model answers, what can be chosen, and a short try-it (stage D, step D2).
import type { Transport } from "@wasifyai/client";
import { HttpError } from "@wasifyai/client";
import type { FoundModel } from "./discovery";

export type Selection = {
  kind: "file" | "server";
  name: string;
  context: number;
  path: string | null;
  tool: string | null;
  url: string | null;
  model: string | null;
  note: string;
};

export type LanguageFile = FoundModel & { chosen: boolean };

export type LanguageServer = {
  tool: string;
  title: string;
  url: string;
  model: string;
  chosen: boolean;
};

export type LanguageState = {
  selected: Selection | null;
  contexts: number[];
  engine: { installed: boolean; version: string | null; backend: string | null; running: boolean };
  files: LanguageFile[];
  servers: LanguageServer[];
};

export type Choice =
  | { item_id: string; context: number }
  | { server: { tool: string; url: string; model: string }; context: number }
  | { clear: true };

/** "8K", "32K": a context length for a person. */
export function contextLabel(tokens: number): string {
  return tokens >= 1024 ? `${Math.round(tokens / 1024)}K` : String(tokens);
}

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

export function createLanguageApi(transport: Transport) {
  const headers = { "content-type": "application/json" };
  return {
    state: () => json<LanguageState>(transport, "/desktop/language"),
    choose: (choice: Choice) =>
      json<{ selected: Selection | null }>(transport, "/desktop/language", {
        method: "PUT",
        headers,
        body: JSON.stringify(choice),
      }),
    tryIt: (prompt: string) =>
      json<{ text: string; seconds: number; model: string }>(transport, "/desktop/language/try", {
        method: "POST",
        headers,
        body: JSON.stringify({ prompt }),
      }),
  };
}

export type LanguageApi = ReturnType<typeof createLanguageApi>;
