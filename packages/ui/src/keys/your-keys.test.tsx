// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { KeyChoice, KeyProduct, OwnKeys, OwnKeysApi } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { YourKeys } from "./YourKeys";

const product = (over: Partial<KeyProduct>): KeyProduct => ({
  id: "chat",
  title: "Chat and writing",
  kind: "text",
  mode: "here",
  provider: null,
  model: null,
  base_url: null,
  key_saved: false,
  state: "here",
  said: null,
  tested_at: null,
  models: [],
  ...over,
});

const providers: OwnKeys["providers"] = [
  {
    id: "openrouter",
    title: "OpenRouter",
    kind: "text",
    host: "openrouter.ai",
    needs_base: false,
    models: ["openai/gpt-4o-mini"],
  },
  {
    id: "compatible",
    title: "Another OpenAI-compatible server",
    kind: "text",
    host: "",
    needs_base: true,
    models: [],
  },
  { id: "fal", title: "fal.ai", kind: "media", host: "fal.ai", needs_base: false, models: [] },
];

function keys(products: KeyProduct[], can_save = true): OwnKeys {
  return { products, providers, can_save };
}

/** A fake engine: a key with "good" in it is accepted; what was sent is kept. */
function fakeApi(start: OwnKeys) {
  let state = start;
  const set = (id: string, change: Partial<KeyProduct>) => {
    state = {
      ...state,
      products: state.products.map((p) => (p.id === id ? { ...p, ...change } : p)),
    };
    return state;
  };
  const api = {
    list: vi.fn(async () => state),
    test: vi.fn(async (_id: string, c: KeyChoice) =>
      c.key?.includes("good")
        ? { ok: true, ms: 840, said: null }
        : { ok: false, ms: 5, said: "OpenRouter did not accept the key." },
    ),
    save: vi.fn(async (id: string, mode: "here" | "key", c: KeyChoice = {}) => {
      if (mode === "here") return set(id, { mode: "here", state: "here" });
      if (!c.key?.includes("good") && !state.products.find((p) => p.id === id)?.key_saved) {
        throw new Error("OpenRouter did not accept the key.");
      }
      return set(id, {
        mode: "key",
        state: "ok",
        provider: c.provider ?? null,
        model: c.model ?? null,
        key_saved: true,
      });
    }),
    check: vi.fn(async () => state),
    copy: vi.fn(async (id: string) => set(id, { key_saved: true, provider: "fal" })),
    remove: vi.fn(async (id: string) =>
      set(id, { mode: "here", state: "here", key_saved: false, provider: null, model: null }),
    ),
  };
  return api as typeof api & OwnKeysApi;
}

describe("Your keys", () => {
  it("lists every product with where it runs, and a key that stopped working says why", async () => {
    const api = fakeApi(
      keys([
        product({}),
        product({
          id: "images",
          title: "Images",
          kind: "media",
          mode: "key",
          state: "ok",
          provider: "fal",
          model: "fal-ai/flux-2",
          key_saved: true,
        }),
        product({
          id: "video",
          title: "Video",
          kind: "media",
          mode: "key",
          state: "bad",
          provider: "fal",
          model: "fal-ai/ltx-2/text-to-video/fast",
          key_saved: true,
          said: "fal.ai did not accept the key.",
        }),
      ]),
    );
    render(<YourKeys api={api} />);
    const table = await screen.findByRole("table", { name: "Products and their keys" });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Chat and writing");
    expect(rows[1]).toHaveTextContent("On this computer");
    expect(rows[2]).toHaveTextContent("fal.ai · fal-ai/flux-2");
    expect(rows[3]).toHaveTextContent("Key not working");
    expect(rows[3]).toHaveTextContent("fal.ai did not accept the key.");
    expect(
      within(rows[3] as HTMLElement).getByRole("button", { name: "Change Video" }),
    ).toHaveTextContent("Fix");
  });

  it("tests without saving, then saves a key that works, and never shows it", async () => {
    const user = userEvent.setup();
    const api = fakeApi(keys([product({})]));
    render(<YourKeys api={api} />);
    await user.click(
      await screen.findByRole("button", { name: "Use my key for Chat and writing" }),
    );
    const box = screen.getByRole("region", { name: "Chat and writing: where it runs" });
    expect(within(box).getByLabelText("Model")).toHaveProperty("value", "openai/gpt-4o-mini");
    expect(box).toHaveTextContent("sent to openrouter.ai with this key");
    await user.type(within(box).getByLabelText("Key"), "sk-bad");
    await user.click(within(box).getByRole("button", { name: "Test" }));
    expect(await within(box).findByText("OpenRouter did not accept the key.")).toBeTruthy();
    expect(api.save).not.toHaveBeenCalled();
    await user.clear(within(box).getByLabelText("Key"));
    await user.type(within(box).getByLabelText("Key"), "sk-good");
    await user.click(within(box).getByRole("button", { name: "Test" }));
    expect(
      await within(box).findByText(/It answered in 840 ms\. Nothing is saved yet\./),
    ).toBeTruthy();
    await user.click(within(box).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.save).toHaveBeenCalledWith("chat", "key", {
        provider: "openrouter",
        model: "openai/gpt-4o-mini",
        key: "sk-good",
      }),
    );
    // the box closes and the row says where it runs now
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Chat and writing: where it runs" })).toBeNull(),
    );
    expect(screen.getByRole("table")).toHaveTextContent("OpenRouter · openai/gpt-4o-mini");
    expect(document.body.textContent).not.toContain("sk-good");
  });

  it("asks for the address of another OpenAI-compatible server", async () => {
    const user = userEvent.setup();
    const api = fakeApi(keys([product({})]));
    render(<YourKeys api={api} />);
    await user.click(
      await screen.findByRole("button", { name: "Use my key for Chat and writing" }),
    );
    await user.click(screen.getByRole("combobox", { name: "Provider" }));
    await user.click(
      await screen.findByRole("option", { name: "Another OpenAI-compatible server" }),
    );
    await user.type(screen.getByLabelText("Model"), "llama3");
    await user.type(screen.getByLabelText("The server's address"), "http://192.168.1.5:8000/v1");
    await user.type(screen.getByLabelText("Key"), "good-key");
    await user.click(screen.getByRole("button", { name: "Test" }));
    await waitFor(() =>
      expect(api.test).toHaveBeenCalledWith("chat", {
        provider: "compatible",
        model: "llama3",
        base_url: "http://192.168.1.5:8000/v1",
        key: "good-key",
      }),
    );
  });

  it("uses the same key as another product of its kind, copied in the engine", async () => {
    const user = userEvent.setup();
    const api = fakeApi(
      keys([
        product({
          id: "images",
          title: "Images",
          kind: "media",
          mode: "key",
          state: "ok",
          provider: "fal",
          model: "fal-ai/flux-2",
          key_saved: true,
        }),
        product({ id: "voice", title: "Voice", kind: "media", models: ["fal-ai/kokoro"] }),
        product({ id: "chat", title: "Chat and writing", key_saved: true }),
      ]),
    );
    render(<YourKeys api={api} />);
    await user.click(await screen.findByRole("button", { name: "Use my key for Voice" }));
    const box = screen.getByRole("region", { name: "Voice: where it runs" });
    expect(within(box).queryByText("Use the same key as Chat and writing")).toBeNull();
    await user.click(within(box).getByRole("button", { name: "Use the same key as Images" }));
    await waitFor(() => expect(api.copy).toHaveBeenCalledWith("voice", "images"));
    // the key is saved now: Save works without pasting it again
    await user.click(within(box).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.save).toHaveBeenCalledWith("voice", "key", {
        provider: "fal",
        model: "fal-ai/kokoro",
      }),
    );
  });

  it("goes back to this computer, and removes a key after asking", async () => {
    const user = userEvent.setup();
    const api = fakeApi(
      keys([
        product({
          mode: "key",
          state: "ok",
          provider: "openrouter",
          model: "openai/gpt-4o-mini",
          key_saved: true,
        }),
      ]),
    );
    render(<YourKeys api={api} />);
    await user.click(await screen.findByRole("button", { name: "Change Chat and writing" }));
    await user.click(screen.getByRole("radio", { name: "On this computer" }));
    expect(screen.getByText(/Your key stays saved until you remove it/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.save).toHaveBeenCalledWith("chat", "here", {}));

    await user.click(
      await screen.findByRole("button", { name: "Use my key for Chat and writing" }),
    );
    await user.click(screen.getByRole("button", { name: "Remove the key" }));
    expect(api.remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith("chat"));
  });

  it("says when this computer cannot keep a key, and offers nothing to change", async () => {
    render(<YourKeys api={fakeApi(keys([product({})], false))} />);
    expect(await screen.findByText("Keys cannot be kept here")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Use my key for Chat and writing" })).toBeDisabled();
  });
});
