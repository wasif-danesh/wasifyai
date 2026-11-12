// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import type { OwnKeysApi } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { ServiceKeys } from "./ServiceKeys";

// Admin › Media on the cloud-only web (ADR-0100, CP11): the service's keys, and the cloud model each product runs on.
vi.mock("@/lib/run-client", () => ({ transport: { fetch: vi.fn() } }));

const products = [
  {
    id: "media",
    title: "Every media product",
    kind: "media",
    providers: ["runware", "wavespeed", "fal"],
    keys: [{ provider: "fal", state: "ok", said: null, tested_at: 1 }],
    use: null,
  },
  {
    id: "images",
    title: "Images",
    kind: "media",
    providers: ["runware", "wavespeed", "fal"],
    keys: [],
    use: { provider: "fal", model: "gpt-image-2.5", title: "GPT Image 2.5", price: "" },
  },
];

function api(): OwnKeysApi {
  return {
    list: vi.fn(async () => ({ products, providers: [], can_save: true })),
    cloud: vi.fn(async (p: string) => ({
      product: p,
      has_keys: true,
      models: [
        {
          provider: "fal",
          provider_title: "fal.ai",
          host: "fal.ai",
          model: "gpt-image-2.5",
          title: "GPT Image 2.5",
          about: "",
          price: "from $0.04 per picture",
          providers: ["fal"],
          cheaper_with: null,
          works: true,
          chosen: true,
        },
      ],
    })),
    use: vi.fn(),
    save: vi.fn(),
    remove: vi.fn(),
    check: vi.fn(),
    test: vi.fn(),
  } as unknown as OwnKeysApi;
}

describe("Admin › Media", () => {
  it("shows the service's keys in the service's words and each product's cloud model", async () => {
    render(<ServiceKeys api={api()} />);
    expect(await screen.findByRole("heading", { name: "Service keys" })).toBeTruthy();
    expect(screen.getByText(/encrypted in the service's database/)).toBeTruthy();
    expect(screen.queryByText(/keychain/)).toBeNull();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Models" })).toBeTruthy());
    // the media row "Every media product" holds keys only; Images has its model
    expect(await screen.findByText(/GPT Image 2.5 · from \$0.04 per picture/)).toBeTruthy();
  });
});
