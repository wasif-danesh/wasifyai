// The chat on the person's own Claude or ChatGPT plan (ADR-0110): which plan the chat answers on, and the models each
// program offers it. The engine's `/desktop/chat-plan` routes. Setting up the programs and signing in are Code's
// (ADR-0107); nothing here carries a login or a token.
import type { Transport } from "./transport";
import { HttpError } from "./transport";

/** The plan the chat answers on: a program and its model ("" is the program's own choice). */
export type ChatPlanChoice = { harness: string; model: string };

export type ChatPlanProgram = { id: string; title: string; models: { id: string; name: string }[] };

export type ChatPlan = { choice: ChatPlanChoice | null; programs: ChatPlanProgram[] };

const BASE = "/desktop/chat-plan";

async function json<T>(transport: Transport, init?: RequestInit): Promise<T> {
  const res = await transport.fetch(BASE, init);
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

export function createChatPlanApi(transport: Transport) {
  return {
    get: () => json<ChatPlan>(transport),
    /** Make the chat answer on a plan, or on its model again (`null`). */
    use: (choice: ChatPlanChoice | null) =>
      json<ChatPlan>(transport, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(choice ?? { harness: null }),
      }),
  };
}

export type ChatPlanApi = ReturnType<typeof createChatPlanApi>;
