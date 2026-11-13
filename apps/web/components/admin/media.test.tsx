// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MediaBackend, MediaView } from "@wasifyai/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiSend = vi.fn();
vi.mock("@/lib/api", () => ({ apiSend: (...a: unknown[]) => apiSend(...a) }));
vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

const KEY = "comfyui-0123456789abcdef0123456789abcdef";

const backends: MediaBackend[] = [
  {
    id: "comfyui-local",
    label: "ComfyUI (local or self-hosted)",
    description: "Runs the workflow on your ComfyUI server.",
    families: ["image", "music"],
    fields: [
      {
        name: "base_url",
        label: "Server address",
        required: false,
        secret: false,
        placeholder: "http://x:8188",
        help: "",
      },
    ],
  },
  {
    id: "comfy-api",
    label: "Comfy Cloud / Comfy API (v2)",
    description: "Runs the workflow on Comfy Cloud.",
    families: ["image", "music"],
    fields: [
      {
        name: "base_url",
        label: "API address",
        required: false,
        secret: false,
        placeholder: "https://cloud.comfy.org",
        help: "",
      },
      {
        name: "api_key",
        label: "API key",
        required: true,
        secret: true,
        placeholder: "",
        help: "",
      },
    ],
  },
  {
    id: "openai-images",
    label: "OpenAI-compatible image API",
    description: "Sends the prompt to /images/generations.",
    families: ["image"],
    fields: [
      {
        name: "model",
        label: "Model",
        required: true,
        secret: false,
        placeholder: "gpt-image-1",
        help: "",
      },
      {
        name: "api_key",
        label: "API key",
        required: false,
        secret: true,
        placeholder: "",
        help: "",
      },
    ],
  },
];

const item = (over: Partial<MediaView> = {}): MediaView => ({
  product_id: "wasifyai-music",
  capability: "image.generate",
  workflow: "flux2",
  backend: "comfyui-local",
  source: "default",
  config: {},
  key_set: false,
  allowed_backends: ["comfyui-local", "comfy-api", "openai-images"],
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

describe("submitMedia (the server action)", () => {
  it("sends the settings and the key once, and never echoes the key back", async () => {
    apiSend.mockResolvedValue({ status: 200, data: { ok: true, message: "fine", latency_ms: 5 } });
    const { submitMedia } = await import("../../app/(site)/admin/media/actions");
    const out = await submitMedia(
      "wasifyai-music",
      "image.generate",
      { status: "idle" },
      form({
        intent: "test",
        backend: "comfy-api",
        cfg_base_url: " https://c.example ",
        cfg_model: "",
        api_key: KEY,
      }),
    );
    expect(apiSend).toHaveBeenCalledWith(
      "POST",
      "/admin/media/wasifyai-music/image.generate/test",
      {
        backend: "comfy-api",
        config: { base_url: "https://c.example" }, // blank settings are not sent
        api_key: KEY,
        key_from: null,
      },
    );
    expect(out.status).toBe("tested");
    expect(JSON.stringify(out)).not.toContain(KEY);
  });

  it("saves with PUT and reports problems in words", async () => {
    const { submitMedia } = await import("../../app/(site)/admin/media/actions");
    apiSend.mockResolvedValueOnce({ status: 200, data: {} });
    expect(
      (
        await submitMedia(
          "p",
          "image.generate",
          { status: "idle" },
          form({ intent: "save", backend: "comfy-api" }),
        )
      ).status,
    ).toBe("saved");
    expect(apiSend.mock.calls[0].slice(0, 2)).toEqual(["PUT", "/admin/media/p/image.generate"]);
    apiSend.mockResolvedValueOnce({
      status: 422,
      data: { detail: "Comfy Cloud needs an api key" },
    });
    const bad = await submitMedia(
      "p",
      "image.generate",
      { status: "idle" },
      form({ intent: "save", backend: "comfy-api" }),
    );
    expect(bad).toEqual({ status: "error", message: "Comfy Cloud needs an api key" });
    apiSend.mockResolvedValueOnce({ status: 403, data: {} });
    expect(
      (await submitMedia(
        "p",
        "image.generate",
        { status: "idle" },
        form({ intent: "save", backend: "x" }),
      )) as { message: string },
    ).toMatchObject({ message: expect.stringContaining("Only admins") });
  });

  it("sends the row whose key is used, and nothing when none is chosen", async () => {
    apiSend.mockResolvedValue({ status: 200, data: {} });
    const { submitMedia } = await import("../../app/(site)/admin/media/actions");
    await submitMedia(
      "wasifyai-voice",
      "speech.speak",
      { status: "idle" },
      form({
        intent: "save",
        backend: "fal",
        cfg_model: "fal-ai/kokoro",
        key_from: "wasifyai-image/image.generate",
      }),
    );
    expect(apiSend.mock.calls[0][2]).toEqual({
      backend: "fal",
      config: { model: "fal-ai/kokoro" },
      api_key: null,
      key_from: "wasifyai-image/image.generate",
    });
    await submitMedia(
      "wasifyai-voice",
      "speech.speak",
      { status: "idle" },
      form({ intent: "save", backend: "fal", cfg_model: "m", api_key: "k", key_from: "none" }),
    );
    expect(apiSend.mock.calls[1][2]).toMatchObject({ api_key: "k", key_from: null });
  });

  it("resets without a body and refuses odd names before calling the API", async () => {
    apiSend.mockResolvedValue({ status: 200, data: {} });
    const { submitMedia } = await import("../../app/(site)/admin/media/actions");
    expect(
      (await submitMedia("p", "music.generate", { status: "idle" }, form({ intent: "reset" })))
        .status,
    ).toBe("reset");
    expect(apiSend).toHaveBeenCalledWith("POST", "/admin/media/p/music.generate/reset");
    apiSend.mockClear();
    expect(
      (await submitMedia("../x", "image.generate", { status: "idle" }, form({ intent: "save" })))
        .status,
    ).toBe("error");
    expect(apiSend).not.toHaveBeenCalled();
  });
});

describe("MediaForm", () => {
  async function renderForm(m: MediaView, secretsReady = true) {
    const { MediaForm } = await import("./MediaForm");
    render(<MediaForm item={m} backends={backends} secretsReady={secretsReady} />);
  }

  it("shows each backend's own fields, and a password box only where a key is used", async () => {
    await renderForm(item());
    expect(screen.getByLabelText(/Server address/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/API key/)).not.toBeInTheDocument();
    await choose("Runs on", /Comfy Cloud/);
    expect(screen.getByLabelText(/API key/)).toHaveAttribute("type", "password");
    await choose("Runs on", /OpenAI/);
    expect(screen.getByLabelText(/^Model/)).toBeRequired();
    expect(screen.getByLabelText(/API key \(optional\)/)).toBeInTheDocument();
  });

  it("only offers the backends the capability can use", async () => {
    await renderForm(
      item({ capability: "music.generate", allowed_backends: ["comfyui-local", "comfy-api"] }),
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Runs on" }));
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options).toEqual(["ComfyUI (local or self-hosted)", "Comfy Cloud / Comfy API (v2)"]);
  });

  it("starts with an empty write-only key and says a saved one is kept", async () => {
    await renderForm(item({ backend: "comfy-api", source: "custom", key_set: true }));
    const key = screen.getByLabelText(/API key/);
    expect(key).toHaveValue("");
    expect(key).toHaveAttribute("placeholder", expect.stringContaining("Leave empty to keep"));
    expect(screen.getByRole("button", { name: "Reset to default" })).toBeInTheDocument();
  });

  it("offers the key of another row on the same service, and then needs none typed", async () => {
    const { MediaForm } = await import("./MediaForm");
    render(
      <MediaForm
        item={item({ capability: "image.edit", backend: "comfy-api" })}
        backends={backends}
        secretsReady
        keyRows={[
          { id: "p/image.generate", backend: "comfy-api", label: "p · image.generate" },
          { id: "q/music.generate", backend: "comfyui-local", label: "q · music.generate" },
        ]}
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Or use a key already saved" }));
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options).toEqual(["No, use the key above", "Use the key saved for p · image.generate"]);
    await userEvent.click(screen.getByRole("option", { name: /p · image.generate/ }));
    expect(screen.getByLabelText(/API key/)).toBeDisabled();
  });

  it("disables the key box until the encryption key exists", async () => {
    await renderForm(item({ backend: "comfy-api" }), false);
    expect(screen.getByLabelText(/API key/)).toBeDisabled();
    expect(screen.getByText(/MEDIA_SECRETS_KEY/)).toBeInTheDocument();
  });
});
