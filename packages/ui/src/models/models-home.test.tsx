// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModelsHome, tableOrder } from "./ModelsHome";
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

function page(src: never, props: Record<string, unknown> = {}) {
  return render(
    <ModelChoicesProvider source={src}>
      <ModelsHome {...props} />
    </ModelChoicesProvider>,
  );
}

afterEach(cleanup);

describe("the Models page", () => {
  it("has a tab for every group, named for the job, and says what the computer has", async () => {
    const { src } = source({});
    page(src);
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(GROUPS.map((g) => g.title));
    expect(await screen.findByTestId("machine")).toHaveProperty(
      "textContent",
      expect.stringContaining("32 GB of memory"),
    );
  });

  it("shows the models of a tab as a table: name, size, state and one action", async () => {
    const { src } = source({
      voice: [
        row({ chosen: true }),
        row({
          id: "m2",
          title: "VoxCPM2",
          state: "needs_download",
          downloadBytes: 4e9,
          sizeBytes: 0,
          tier: "also",
        }),
      ],
    });
    const user = userEvent.setup();
    page(src);
    await user.click(await screen.findByRole("tab", { name: "Voice" }));
    const table = await screen.findByRole("table", { name: "Voice models" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3); // the header and two models
    const kokoro = within(rows[1] as HTMLElement);
    expect(kokoro.getAllByText("Kokoro 82M").length).toBeGreaterThan(0);
    expect(kokoro.getByText("330 MB")).toBeTruthy();
    expect(kokoro.getByText("In use")).toBeTruthy();
    const vox = within(rows[2] as HTMLElement);
    expect(vox.getByText("4.0 GB")).toBeTruthy();
    expect(vox.getByText("Not downloaded")).toBeTruthy();
    expect(vox.getByRole("button", { name: /Get/ })).toBeTruthy();
  });

  it("puts what is in use first, then what is here, then the recommended, then the rest", () => {
    const names = tableOrder([
      row({ id: "a", title: "far", state: "needs_download", tier: "advanced" }),
      row({ id: "b", title: "rec", state: "needs_download", tier: "recommended" }),
      row({ id: "c", title: "here", state: "ready" }),
      row({ id: "d", title: "use", state: "ready", chosen: true }),
    ]).map((c) => c.title);
    expect(names).toEqual(["use", "here", "rec", "far"]);
  });

  it("uses a model that is here, and asks before it downloads one that is not", async () => {
    const choose = vi.fn(async () => {});
    const get = vi.fn(async () => {});
    const rows = [
      row({ id: "here", title: "Here", chosen: false }),
      row({ id: "far", title: "Far", state: "needs_download", downloadBytes: 2e9 }),
    ];
    const src = (() => ({
      list: async () => ({ choices: rows, diskFreeBytes: 200e9, memoryBytes: 32e9 }),
      choose,
      get,
    })) as never;
    const user = userEvent.setup();
    page(src, { initialGroup: "voice" });
    await user.click(await screen.findByRole("button", { name: /Use Here/ }));
    await waitFor(() => expect(choose).toHaveBeenCalledWith("here"));
    await user.click(screen.getByRole("button", { name: /Get Far/ }));
    const dialog = await screen.findByRole("dialog", { name: "Download Far?" });
    expect(dialog.textContent).toContain("It runs on this computer");
    expect(get).not.toHaveBeenCalled(); // not until the person says yes
    await user.click(within(dialog).getByRole("button", { name: "Download and use" }));
    await waitFor(() => expect(get).toHaveBeenCalled());
  });

  it("takes one off after asking", async () => {
    const { src, remove } = source({ voice: [row({ chosen: true })] });
    const user = userEvent.setup();
    page(src);
    await user.click(await screen.findByRole("tab", { name: "Voice" }));
    await user.click(await screen.findByRole("button", { name: /Remove Kokoro 82M/ }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Kokoro 82M?" });
    expect(dialog.textContent).toContain("frees 330 MB");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("m1"));
  });

  it("moves between tabs with the arrow keys", async () => {
    const { src } = source({});
    const user = userEvent.setup();
    page(src);
    const first = await screen.findByRole("tab", { name: GROUPS[0]?.title ?? "" });
    first.focus();
    await user.keyboard("{ArrowRight}");
    expect(
      screen.getByRole("tab", { name: GROUPS[1]?.title ?? "" }).getAttribute("aria-selected"),
    ).toBe("true");
  });

  it("on a service says the models are on the workers and has a tab only for groups it serves", async () => {
    const choices = (group: string) =>
      group === "voice" || group === "music"
        ? {
            list: async () => ({
              choices: [row({ state: "needs_download", downloadBytes: 1e9 })],
              diskFreeBytes: null,
              memoryBytes: null,
            }),
            choose: async () => {},
            get: async () => {},
          }
        : null;
    page(choices as never, { place: "service" });
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Voice", "Music"]);
    expect(screen.getByText(/models on this service's workers/i)).toBeTruthy();
    expect(await screen.findByText("Not on the worker")).toBeTruthy();
    expect(screen.queryByTestId("machine")).toBeNull();
  });

  it("keeps Advanced shut until asked", async () => {
    const { src } = source({});
    page(src, { advanced: <p>Folders</p> });
    const details = (await screen.findByText("Advanced")).closest("details");
    expect(details?.open).toBe(false);
  });
});
