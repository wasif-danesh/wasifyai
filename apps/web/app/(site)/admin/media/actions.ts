"use server";

import { apiSend } from "@/lib/api";
import type { MediaTestOutcome } from "@wasifyai/contracts";
import { revalidatePath } from "next/cache";

export type MediaFormState =
  | { status: "idle" }
  | { status: "tested"; outcome: MediaTestOutcome }
  | { status: "saved" }
  | { status: "reset" }
  | { status: "error"; message: string };

const PART = /^[a-z0-9][a-z0-9._-]{0,63}$/;

function text(form: FormData, name: string): string {
  const v = form.get(name);
  return typeof v === "string" ? v.trim() : "";
}

function problem(status: number, data: unknown): MediaFormState {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (status === 401) return { status: "error", message: "Your session ended. Sign in again." };
  if (status === 403) return { status: "error", message: "Only admins can change media settings." };
  return {
    status: "error",
    message: typeof detail === "string" ? detail : `The server answered ${status}.`,
  };
}

/** One form, three buttons (`intent`: test, save, reset). Settings are the `cfg_*` fields; the API
 * key is passed through once and is never part of the state sent back to the page. */
export async function submitMedia(
  product: string,
  capability: string,
  _previous: MediaFormState,
  form: FormData,
): Promise<MediaFormState> {
  if (!PART.test(product) || !PART.test(capability)) {
    return { status: "error", message: "Unknown capability." };
  }
  const path = `/admin/media/${product}/${capability}`;
  const intent = text(form, "intent");

  if (intent === "reset") {
    const { status, data } = await apiSend("POST", `${path}/reset`);
    if (status !== 200) return problem(status, data);
    revalidatePath("/admin/media");
    return { status: "reset" };
  }

  const config: Record<string, string> = {};
  form.forEach((value, name) => {
    if (name.startsWith("cfg_") && typeof value === "string" && value.trim()) {
      config[name.slice(4)] = value.trim();
    }
  });
  const binding = {
    backend: text(form, "backend"),
    config,
    api_key: text(form, "api_key") || null,
    // "Use the key saved for …": another row on the same service (ADR-0095 K5)
    key_from: ["", "none"].includes(text(form, "key_from")) ? null : text(form, "key_from"),
  };

  if (intent === "test") {
    const { status, data } = await apiSend("POST", `${path}/test`, binding);
    return status === 200
      ? { status: "tested", outcome: data as MediaTestOutcome }
      : problem(status, data);
  }
  if (intent === "save") {
    const { status, data } = await apiSend("PUT", path, binding);
    if (status !== 200) return problem(status, data);
    revalidatePath("/admin/media");
    return { status: "saved" };
  }
  return { status: "error", message: "Unknown action." };
}
