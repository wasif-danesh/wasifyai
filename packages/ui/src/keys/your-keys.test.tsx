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

const row = (name: string) => screen.getByRole("region", { name });

const media = (over: Partial<KeyProduct> = {}) =>
  product({
    id: "media",
    title: "Media",
    kind: "media",
    providers: ["runware", "wavespeed", "fal"],
    ...over,
  });
const served = (id: string, title: string, offered: string[]) =>
  product({ id, title, kind: "media", providers: offered });
const mediaProviders: OwnKeys["providers"] = [
  { id: "runware", title: "Runware", host: "runware.ai" },
  { id: "wavespeed", title: "WaveSpeed", host: "wavespeed.ai" },
  ...providers,
];

describe("Cloud keys", () => {
  it("keeps media keys once, under Media, with a row per provider", async () => {
    const api = fakeApi({
      products: [
        product({}),
        media({ keys: [saved("fal", { state: "bad", said: "Key was revoked." })] }),
        served("images", "Images", ["runware", "wavespeed", "fal"]),
      ],
      providers: mediaProviders,
      can_save: true,
    });
    render(<YourKeys api={api} />);
    const chat = await screen.findByRole("region", { name: "Chat and writing" });
    expect(chat).toHaveTextContent("No key: chat and writing uses this computer's models only.");
    const keys = row("Media");
    expect(keys).toHaveTextContent("add a fal.ai key, or both a Runware and a WaveSpeed key");
    expect(keys).toHaveTextContent("fal.aiKey not working");
    expect(keys).toHaveTextContent("Key was revoked.");
    expect(within(keys).getByRole("button", { name: "Add a Runware key" })).toBeTruthy();
    expect(within(keys).getByRole("button", { name: "Add a WaveSpeed key" })).toBeTruthy();
    // no product has keys of its own, and none is named a model
    expect(screen.queryByRole("button", { name: /Add a key for Images/ })).toBeNull();
  });

  it("shows which provider serves each product and names what no key covers", async () => {
    const user = userEvent.setup();
    const api = fakeApi({
      products: [
        media({ keys: [saved("runware")] }),
        served("images", "Images", ["runware", "wavespeed", "fal"]),
        served("video", "Video", ["runware", "wavespeed", "fal"]),
        served("sfx", "Sound effects", ["wavespeed", "fal"]),
        served("train", "Train models", ["runware", "fal"]),
      ],
      providers: mediaProviders,
      can_save: true,
    });
    render(<YourKeys api={api} />);
    const table = await screen.findByRole("table", { name: /Which provider serves each/ });
    // products the same providers serve share a row
    expect(within(table).getByRole("rowheader", { name: "Images, Video" })).toBeTruthy();
    const sfx = within(table).getByRole("row", { name: /Sound effects/ });
    expect(sfx).toHaveTextContent("Needs a WaveSpeed or fal.ai key");
    expect(within(sfx).getByRole("img", { name: "Not offered" })).toBeTruthy();
    expect(within(sfx).getAllByRole("img", { name: "Offered, no key saved" })).toHaveLength(2);
    const train = within(table).getByRole("row", { name: /Train models/ });
    expect(within(train).getByRole("img", { name: "Covered by your key" })).toBeTruthy();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Your keys cover 3 of 4 media products. The rest run on this computer's models.",
    );
    // a fal.ai key covers the rest
    const keys = row("Media");
    await user.click(within(keys).getByRole("button", { name: "Add a fal.ai key" }));
    const form = screen.getByRole("region", { name: "Add a key for Media" });
    expect(within(form).getByText("Your fal.ai key")).toBeTruthy();
    await user.type(within(form).getByLabelText("Key"), "fal-good");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Your keys cover every media product."),
    );
    expect(api.save).toHaveBeenCalledWith("media", "fal", { key: "fal-good" });
    expect(screen.queryByText(/Needs a/)).toBeNull();
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
    const chat = await screen.findByRole("region", { name: "Chat and writing" });
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
    await waitFor(() => expect(row("Chat and writing")).toHaveTextContent("Works"));
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
    expect(row("Chat and writing")).not.toHaveTextContent("Works");
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
      expect(row("Chat and writing")).toHaveTextContent("No key: chat and writing"),
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
