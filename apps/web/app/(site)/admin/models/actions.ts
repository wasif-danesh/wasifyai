"use server";

import { apiSend } from "@/lib/api";
import type { ModelUpdated, TestOutcome } from "@wasifyai/contracts";
import { revalidatePath } from "next/cache";

export type FormState =
  | { status: "idle" }
  | { status: "tested"; outcome: TestOutcome }
  | { status: "saved"; checks: string }
  | { status: "reset" }
  | { status: "rejected"; message: string; failures: string[] }
  | { status: "error"; message: string };

const ALIAS = /^[a-z0-9][a-z0-9-]{0,40}$/;

function text(form: FormData, name: string): string {
  const v = form.get(name);
  return typeof v === "string" ? v.trim() : "";
}

/** Reasons the API gives for refusing a request, in words for the form. */
function problem(status: number, data: unknown): FormState {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (status === 409 && detail && typeof detail === "object") {
    const d = detail as { message?: string; failures?: string[] };
    return {
      status: "rejected",
      message: d.message ?? "The new model did not pass the checks.",
      failures: d.failures ?? [],
    };
  }
  if (status === 401) return { status: "error", message: "Your session ended. Sign in again." };
  if (status === 403) return { status: "error", message: "Only admins can change models." };
  return {
    status: "error",
    message: typeof detail === "string" ? detail : `The server answered ${status}.`,
  };
}

/** One form, three buttons: `intent` is test, save or reset. The API key is passed through once
 * and is never part of the state sent back to the page. */
export async function submitModel(
  alias: string,
  _previous: FormState,
  form: FormData,
): Promise<FormState> {
  if (!ALIAS.test(alias)) return { status: "error", message: "Unknown model." };
  const intent = text(form, "intent");
  const path = `/admin/models/${alias}`;

  if (intent === "reset") {
    const { status, data } = await apiSend("POST", `${path}/reset`);
    if (status !== 200) return problem(status, data);
    revalidatePath("/admin/models");
    return { status: "reset" };
  }

  const binding = {
    provider: text(form, "provider"),
    model: text(form, "model"),
    api_base: text(form, "api_base") || null,
    api_key: text(form, "api_key") || null,
  };
  if (intent === "test") {
    const { status, data } = await apiSend("POST", `${path}/test`, binding);
    return status === 200
      ? { status: "tested", outcome: data as TestOutcome }
      : problem(status, data);
  }
  if (intent === "save") {
    const { status, data } = await apiSend("PUT", path, binding);
    if (status !== 200) return problem(status, data);
    revalidatePath("/admin/models");
    return { status: "saved", checks: (data as ModelUpdated).checks };
  }
  return { status: "error", message: "Unknown action." };
}
