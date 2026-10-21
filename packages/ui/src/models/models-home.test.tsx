// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ModelsHome } from "./ModelsHome";
import { ModelChoicesProvider } from "./context";
import { type ChoicesApi, GROUPS, type ModelChoice } from "./types";

const row = (over: Partial<ModelChoice> = {}): ModelChoice => ({
  id: "m1",
  title: "Kokoro 82M",
  plain: "A small, fast voice.",
  tier: "recommended",
  state: "ready",
  chosen: false,
  downloadBytes: 0,
  engineBytes: 0,
  engineName: null,
  fit: "fits",
  fitReason: null,
  licence: "Apache-2.0",
  commercial: "yes",
  licenceUrl: null,
  source: "app",
  sizeBytes: 330_000_000,
  removable: true,
  ...over,
});

function source(rows: Partial<Record<string, ModelChoice[]>>, remove = vi.fn(async () => {})) {
  const apis = new Map<string, ChoicesApi>();
  const src = (group: string) => {
    if (!apis.has(group)) {
      apis.set(group, {
        list: async () => ({
          choices: rows[group] ?? [],
          diskFreeBytes: 200e9,
          memoryBytes: 32e9,
        }),
        choose: async () => {},
        get: async () => {},
        remove,
      });
    }
    return apis.get(group) ?? null;
  };
  return { src: src as never, remove };
}

describe("the Models page", () => {
  it("has a card for every group, named for the job, and says what the computer has", async () => {
    const { src } = source({});
    render(
      <ModelChoicesProvider source={src}>
        <ModelsHome />
      </ModelChoicesProvider>,
    );
    for (const g of GROUPS) {
      expect(await screen.findByRole("region", { name: g.title })).toBeTruthy();
    }
    expect(await screen.findByTestId("machine")).toHaveProperty(
      "textContent",
      expect.stringContaining("32 GB of memory"),
    );
    expect(screen.getByTestId("status-images").textContent).toBe("Nothing downloaded yet");
  });

  it("says which model is in use, and takes one off after asking", async () => {
    const { src, remove } = source({ voice: [row({ chosen: true })] });
    const user = userEvent.setup();
    render(
      <ModelChoicesProvider source={src}>
        <ModelsHome />
      </ModelChoicesProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("status-voice").textContent).toBe("In use: Kokoro 82M"),
    );
    const card = screen.getByRole("region", { name: "Voice" });
    await user.click(within(card).getByText(/On this computer \(1\)/));
    await user.click(within(card).getByRole("button", { name: "Remove Kokoro 82M" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Kokoro 82M?" });
    expect(dialog.textContent).toContain("frees 330 MB");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("m1"));
  });

  it("keeps Advanced shut until asked", async () => {
    const { src } = source({});
    render(
      <ModelChoicesProvider source={src}>
        <ModelsHome advanced={<p>Folders</p>} />
      </ModelChoicesProvider>,
    );
    const details = (await screen.findByText("Advanced")).closest("details");
    expect(details?.open).toBe(false);
  });
});
