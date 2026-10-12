// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ModelView, ProviderView } from "@wasifyai/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiSend = vi.fn();
vi.mock("@/lib/api", () => ({ apiSend: (...a: unknown[]) => apiSend(...a) }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const KEY = "sk-live-0123456789abcdef0123456789abcdef";

const providers: ProviderView[] = [
  {
    id: "ollama",
    label: "Ollama (local)",
    needs_key: false,
    needs_base: true,
    model_hint: "gemma4:e4b",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    needs_key: true,
    needs_base: false,
    model_hint: "gemini-2.5-flash",
  },
];
const model = (over: Partial<ModelView> = {}): ModelView => ({
  alias: "lyrics-writer",
  purpose: "Writes lyrics",
  kind: "chat",
  protected: false,
  source: "default",
  provider: "ollama",
  model: "gemma4:e4b",
  api_base: "http://ollama:11434",
  key_set: false,
  updated_by: null,
  updated_at: null,
  ...over,
});

beforeEach(() => apiSend.mockReset());
afterEach(() => vi.resetModules());

function form(fields: Record<string, string>) {
  const f = new FormData();
  for (const [k, v] of Object.entries(fields)) f.set(k, v);
  return f;
}

/** Pick an option of a Radix select: open it by its label, then click the option. */
async function choose(label: string, option: RegExp) {
  await userEvent.click(screen.getByRole("combobox", { name: label }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

describe("submitModel (the server action)", () => {
  const fields = { provider: "gemini", model: "gemini-2.5-flash", api_key: KEY, api_base: "" };

  it("tests a binding without saving it and never echoes the key", async () => {
    apiSend.mockResolvedValue({
      status: 200,
      data: { ok: true, latency_ms: 40, sample: "ok", error: "" },
    });
    const { submitModel } = await import("../../app/(site)/admin/models/actions");
    const out = await submitModel(
      "lyrics-writer",
      { status: "idle" },
      form({ ...fields, intent: "test" }),
    );
    expect(apiSend).toHaveBeenCalledWith("POST", "/admin/models/lyrics-writer/test", {
      provider: "gemini",
      model: "gemini-2.5-flash",
      api_base: null,
      api_key: KEY,
    });
    expect(out.status).toBe("tested");
    expect(JSON.stringify(out)).not.toContain(KEY);
  });

  it("saves, and reports that the checks passed", async () => {
    apiSend.mockResolvedValue({ status: 200, data: { model: {}, checks: "passed" } });
    const { submitModel } = await import("../../app/(site)/admin/models/actions");
    const out = await submitModel(
      "moderator",
      { status: "idle" },
      form({ ...fields, intent: "save" }),
    );
    expect(apiSend.mock.calls[0].slice(0, 2)).toEqual(["PUT", "/admin/models/moderator"]);
    expect(out).toEqual({ status: "saved", checks: "passed" });
  });

  it("shows why the API refused a model that failed the checks", async () => {
    apiSend.mockResolvedValue({
      status: 409,
      data: { detail: { message: "the product's checks failed", failures: ["cv: allowed"] } },
    });
    const { submitModel } = await import("../../app/(site)/admin/models/actions");
    const out = await submitModel(
      "moderator",
      { status: "idle" },
      form({ ...fields, intent: "save" }),
    );
    expect(out).toEqual({
      status: "rejected",
      message: "the product's checks failed",
      failures: ["cv: allowed"],
    });
  });

  it.each([
    [403, "Only admins"],
    [401, "session ended"],
    [422, "needs an API key"],
  ])("explains a %i answer", async (status, words) => {
    apiSend.mockResolvedValue({ status, data: { detail: "Google Gemini needs an API key" } });
    const { submitModel } = await import("../../app/(site)/admin/models/actions");
    const out = await submitModel("x-y", { status: "idle" }, form({ ...fields, intent: "save" }));
    expect(out.status).toBe("error");
    expect((out as { message: string }).message).toContain(words);
  });

  it("resets without sending a binding, and refuses an odd alias before calling the API", async () => {
    apiSend.mockResolvedValue({ status: 200, data: {} });
    const { submitModel } = await import("../../app/(site)/admin/models/actions");
    expect(
      (await submitModel("embedder", { status: "idle" }, form({ intent: "reset" }))).status,
    ).toBe("reset");
    expect(apiSend).toHaveBeenCalledWith("POST", "/admin/models/embedder/reset");
    apiSend.mockClear();
    const bad = await submitModel("../x", { status: "idle" }, form({ intent: "save" }));
    expect(bad.status).toBe("error");
    expect(apiSend).not.toHaveBeenCalled();
  });
});

describe("ModelForm", () => {
  async function renderForm(m: ModelView) {
    const { ModelForm } = await import("./ModelForm");
    render(<ModelForm model={m} providers={providers} />);
  }

  it("shows the server address for a local provider and the key for a hosted one", async () => {
    await renderForm(model());
    expect(screen.getByLabelText("Server address")).toBeInTheDocument();
    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
    await choose("Provider", /Gemini/);
    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "password");
    expect(screen.queryByLabelText("Server address")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Model")).toHaveAttribute("placeholder", "gemini-2.5-flash");
  });

  it("starts with an empty, write-only key and offers a reset only for a custom binding", async () => {
    await renderForm(
      model({ provider: "gemini", model: "gemini-2.5-flash", source: "custom", key_set: true }),
    );
    expect(screen.getByLabelText("API key")).toHaveValue("");
    expect(screen.getByLabelText("API key")).toHaveAttribute(
      "placeholder",
      expect.stringContaining("saved"),
    );
    expect(screen.getByRole("button", { name: "Reset to default" })).toBeInTheDocument();
  });

  it("has no reset for a default binding, and warns before changing the moderator", async () => {
    await renderForm(model({ protected: true }));
    expect(screen.queryByRole("button", { name: "Reset to default" })).not.toBeInTheDocument();
    expect(screen.getByText(/runs the guardrail test cases/)).toBeInTheDocument();
  });
});
