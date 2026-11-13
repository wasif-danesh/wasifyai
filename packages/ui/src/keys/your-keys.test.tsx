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
  providers: ["openrouter"],
  keys: [],
  use: null,
  ...over,
});

const saved = (provider: string, over: Partial<SavedKey> = {}): SavedKey => ({
  provider,
  state: "ok",
  said: null,
  tested_at: 1,
  ...over,
});

const providers: OwnKeys["providers"] = [
  { id: "openrouter", title: "OpenRouter", host: "openrouter.ai" },
  { id: "fal", title: "fal.ai", host: "fal.ai" },
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
        keys: [...p.keys, saved(provider)],
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
          providers: ["fal"],
          keys: [saved("fal")],
          use: { provider: "fal", model: "fal-ai/infinitalk", title: "InfiniteTalk", price: "" },
        }),
        product({
          id: "music",
          title: "Music",
          kind: "media",
          providers: ["fal"],
          keys: [saved("fal", { state: "bad", said: "Key was revoked." })],
        }),
      ]),
    );
    render(<YourKeys api={api} />);
    const chat = await screen.findByRole("listitem", { name: "Chat and writing" });
    expect(chat).toHaveTextContent("No key: Chat and writing uses this computer's models only.");
    expect(within(chat).getByText("OpenRouter")).toBeTruthy();
    const lipsync = row("Lip sync");
    expect(lipsync).toHaveTextContent("fal.aiSaved · works");
    expect(lipsync).toHaveTextContent("In use: InfiniteTalk");
    // lip sync's one provider has a key: nothing left to add
    expect(within(lipsync).queryByRole("button", { name: /Add a key/ })).toBeNull();
    const music = row("Music");
    expect(music).toHaveTextContent("Key not working");
    expect(music).toHaveTextContent("Key was revoked.");
  });

  it("offers every text vendor for chat, Anthropic first, and saves the one picked", async () => {
    const user = userEvent.setup();
    const vendors = ["anthropic", "openai", "gemini", "deepseek", "zai", "openrouter"];
    const api = fakeApi({
      products: [product({ providers: vendors })],
      providers: [
        { id: "anthropic", title: "Anthropic", host: "api.anthropic.com" },
        { id: "openai", title: "OpenAI", host: "api.openai.com" },
        { id: "gemini", title: "Google Gemini", host: "generativelanguage.googleapis.com" },
        { id: "deepseek", title: "DeepSeek", host: "api.deepseek.com" },
        { id: "zai", title: "Z.ai", host: "api.z.ai" },
        ...providers,
      ],
      can_save: true,
    });
    render(<YourKeys api={api} />);
    const chat = await screen.findByRole("listitem", { name: "Chat and writing" });
    expect(chat).toHaveTextContent("Anthropic, OpenAI, Google Gemini, DeepSeek, Z.ai, OpenRouter");
    await user.click(screen.getByRole("button", { name: "Add a key for Chat and writing" }));
    const form = screen.getByRole("region", { name: "Add a key for Chat and writing" });
    const pick = within(form).getByRole("combobox", { name: "Provider" });
    expect(pick).toHaveTextContent("Anthropic");
    await user.click(pick);
    await user.click(await screen.findByRole("option", { name: "DeepSeek" }));
    await user.type(within(form).getByLabelText("Key"), "sk-good-ds");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.save).toHaveBeenCalledWith("chat", "deepseek", { key: "sk-good-ds" }),
    );
    // five vendors are still there to add
    expect(
      await screen.findByRole("button", { name: "Add a key for Chat and writing" }),
    ).toBeTruthy();
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
    expect(api.test).toHaveBeenCalledWith("chat", "openrouter", { key: "sk-good-1" });
    expect(api.save).not.toHaveBeenCalled();
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(row("Chat and writing")).toHaveTextContent("Saved · works"));
    expect(api.save).toHaveBeenCalledWith("chat", "openrouter", { key: "sk-good-1" });
    expect(document.body.textContent).not.toContain("sk-good-1");
    // OpenRouter has a key now: there is no other text provider to add
    expect(screen.queryByRole("button", { name: "Add a key for Chat and writing" })).toBeNull();
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

  it("tests a saved key again, and removes one after asking", async () => {
    const user = userEvent.setup();
    const api = fakeApi(
      keys([
        product({
          keys: [saved("openrouter")],
          use: {
            provider: "openrouter",
            model: "openai/gpt-4o-mini",
            title: "GPT-4o mini",
            price: "",
          },
        }),
      ]),
    );
    render(<YourKeys api={api} />);
    await user.click(
      await screen.findByRole("button", { name: "Test the OpenRouter key for Chat and writing" }),
    );
    await waitFor(() => expect(row("Chat and writing")).toHaveTextContent("Key not working"));
    expect(api.check).toHaveBeenCalledWith("chat", "openrouter");
    await user.click(
      screen.getByRole("button", { name: "Remove the OpenRouter key for Chat and writing" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("goes back to this computer's model");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(row("Chat and writing")).toHaveTextContent("No key: Chat and writing"),
    );
    expect(api.remove).toHaveBeenCalledWith("chat", "openrouter");
  });

  it("says when this computer cannot keep a key, and offers nothing to add", async () => {
    const api = fakeApi(keys([product({})], false));
    render(<YourKeys api={api} />);
    expect(await screen.findByText("Keys cannot be kept here")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Add a key/ })).toBeNull();
  });
});
