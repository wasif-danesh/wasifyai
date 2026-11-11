// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { KeyBody, KeyProduct, OwnKeys, OwnKeysApi, SavedKey } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { YourKeys } from "./YourKeys";

const product = (over: Partial<KeyProduct>): KeyProduct => ({
  id: "chat",
  title: "Chat and writing",
  kind: "text",
  providers: ["fal", "openrouter", "compatible"],
  keys: [],
  use: null,
  ...over,
});

const saved = (provider: string, over: Partial<SavedKey> = {}): SavedKey => ({
  provider,
  state: "ok",
  said: null,
  tested_at: 1,
  base_url: null,
  model: null,
  ...over,
});

const providers: OwnKeys["providers"] = [
  { id: "fal", title: "fal.ai", host: "fal.ai", needs_base: false },
  { id: "wavespeed", title: "WaveSpeed", host: "wavespeed.ai", needs_base: false },
  { id: "openrouter", title: "OpenRouter", host: "openrouter.ai", needs_base: false },
  { id: "compatible", title: "Another OpenAI-compatible server", host: "", needs_base: true },
];

function keys(products: KeyProduct[], can_save = true): OwnKeys {
  return { products, providers, can_save };
}

/** A fake engine: a key with "good" in it is accepted; what was sent is kept. */
function fakeApi(start: OwnKeys) {
  let state = start;
  const edit = (id: string, fn: (p: KeyProduct) => KeyProduct) => {
    state = { ...state, products: state.products.map((p) => (p.id === id ? fn(p) : p)) };
    return state;
  };
  const api = {
    list: vi.fn(async () => state),
    test: vi.fn(async (_id: string, _provider: string, b: KeyBody = {}) =>
      b.key?.includes("good")
        ? { ok: true, ms: 840, said: null }
        : { ok: false, ms: 5, said: "fal.ai did not accept the key." },
    ),
    save: vi.fn(async (id: string, provider: string, b: KeyBody) => {
      if (!b.key?.includes("good")) throw new Error("fal.ai did not accept the key.");
      return edit(id, (p) => ({
        ...p,
        keys: [
          ...p.keys,
          saved(provider, { base_url: b.base_url ?? null, model: b.model ?? null }),
        ],
      }));
    }),
    check: vi.fn(async (id: string, provider: string) =>
      edit(id, (p) => ({
        ...p,
        keys: p.keys.map((k) =>
          k.provider === provider
            ? { ...k, state: "bad" as const, said: "fal.ai did not accept the key." }
            : k,
        ),
      })),
    ),
    remove: vi.fn(async (id: string, provider: string) =>
      edit(id, (p) => ({
        ...p,
        keys: p.keys.filter((k) => k.provider !== provider),
        use: p.use?.provider === provider ? null : p.use,
      })),
    ),
    cloud: vi.fn(),
    use: vi.fn(),
  };
  return api as typeof api & OwnKeysApi;
}

const row = (name: string) => screen.getByRole("listitem", { name });

describe("Your keys", () => {
  it("lists every product with its saved keys and never a model", async () => {
    const api = fakeApi(
      keys([
        product({}),
        product({
          id: "lipsync",
          title: "Lip sync",
          kind: "media",
          providers: ["fal", "wavespeed"],
          keys: [saved("fal"), saved("wavespeed", { state: "bad", said: "Key was revoked." })],
          use: { provider: "fal", model: "fal-ai/infinitalk", title: "InfiniteTalk", price: "" },
        }),
      ]),
    );
    render(<YourKeys api={api} />);
    const chat = await screen.findByRole("listitem", { name: "Chat and writing" });
    expect(chat).toHaveTextContent("No key: Chat and writing uses this computer's models only.");
    expect(
      within(chat).getByText("fal.ai, OpenRouter, Another OpenAI-compatible server"),
    ).toBeTruthy();
    const lipsync = row("Lip sync");
    expect(lipsync).toHaveTextContent("fal.aiSaved · works");
    expect(lipsync).toHaveTextContent("Key not working");
    expect(lipsync).toHaveTextContent("Key was revoked.");
    expect(lipsync).toHaveTextContent("In use: InfiniteTalk");
    // every provider of lip sync has a key: nothing left to add
    expect(within(lipsync).queryByRole("button", { name: /Add a key/ })).toBeNull();
  });

  it("tests without saving, then saves a key that works, and never shows it", async () => {
    const user = userEvent.setup();
    const api = fakeApi(keys([product({})]));
    render(<YourKeys api={api} />);
    await user.click(await screen.findByRole("button", { name: "Add a key for Chat and writing" }));
    const form = screen.getByRole("region", { name: "Add a key for Chat and writing" });
    await user.type(within(form).getByLabelText("Key"), "sk-good-1");
    await user.click(within(form).getByRole("button", { name: "Test" }));
    expect(await within(form).findByText(/answered in 840 ms/)).toBeTruthy();
    expect(api.test).toHaveBeenCalledWith("chat", "fal", { key: "sk-good-1" });
    expect(api.save).not.toHaveBeenCalled();
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(row("Chat and writing")).toHaveTextContent("Saved · works"));
    expect(api.save).toHaveBeenCalledWith("chat", "fal", { key: "sk-good-1" });
    expect(document.body.textContent).not.toContain("sk-good-1");
    // fal.ai has a key now: it is not offered again
    await user.click(screen.getByRole("button", { name: "Add a key for Chat and writing" }));
    const again = screen.getByRole("region", { name: "Add a key for Chat and writing" });
    expect(within(again).getByRole("combobox")).toHaveTextContent("OpenRouter");
  });

  it("says why a refused key was not saved", async () => {
    const user = userEvent.setup();
    const api = fakeApi(keys([product({})]));
    render(<YourKeys api={api} />);
    await user.click(await screen.findByRole("button", { name: "Add a key for Chat and writing" }));
    const form = screen.getByRole("region", { name: "Add a key for Chat and writing" });
    await user.type(within(form).getByLabelText("Key"), "sk-bad");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("fal.ai did not accept the key.");
    expect(row("Chat and writing")).not.toHaveTextContent("Saved · works");
  });

  it("asks for the address and the model of another OpenAI-compatible server", async () => {
    const user = userEvent.setup();
    const api = fakeApi(keys([product({ providers: ["compatible"] })]));
    render(<YourKeys api={api} />);
    await user.click(await screen.findByRole("button", { name: "Add a key for Chat and writing" }));
    const form = screen.getByRole("region", { name: "Add a key for Chat and writing" });
    await user.type(within(form).getByLabelText("Key"), "good");
    const save = within(form).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await user.type(within(form).getByLabelText("The server's address"), "http://box:8000/v1");
    await user.type(within(form).getByLabelText("The model it runs"), "llama3");
    await user.click(save);
    expect(api.save).toHaveBeenCalledWith("chat", "compatible", {
      key: "good",
      base_url: "http://box:8000/v1",
      model: "llama3",
    });
    await waitFor(() => expect(row("Chat and writing")).toHaveTextContent("llama3"));
  });

  it("tests a saved key again, and removes one after asking", async () => {
    const user = userEvent.setup();
    const api = fakeApi(
      keys([
        product({
          keys: [saved("fal")],
          use: { provider: "fal", model: "openai/gpt-4o-mini", title: "GPT-4o mini", price: "" },
        }),
      ]),
    );
    render(<YourKeys api={api} />);
    await user.click(
      await screen.findByRole("button", { name: "Test the fal.ai key for Chat and writing" }),
    );
    await waitFor(() => expect(row("Chat and writing")).toHaveTextContent("Key not working"));
    expect(api.check).toHaveBeenCalledWith("chat", "fal");
    await user.click(
      screen.getByRole("button", { name: "Remove the fal.ai key for Chat and writing" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("goes back to this computer's model");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(row("Chat and writing")).toHaveTextContent("No key: Chat and writing"),
    );
    expect(api.remove).toHaveBeenCalledWith("chat", "fal");
  });

  it("says when this computer cannot keep a key, and offers nothing to add", async () => {
    const api = fakeApi(keys([product({})], false));
    render(<YourKeys api={api} />);
    expect(await screen.findByText("Keys cannot be kept here")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Add a key/ })).toBeNull();
  });
});
