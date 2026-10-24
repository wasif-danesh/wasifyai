// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchModel = vi.fn(async (_id: string) => "job-1");
const job = vi.fn(async () => ({ status: "done", fraction: 1, label: "", error: null }));
const model = (over: Record<string, unknown>) => ({
  id: "kokoro-82m",
  title: "Kokoro",
  licence: "Apache-2.0",
  engine: "audio.cpp",
  tasks: ["speak"],
  recommended: ["speak"],
  commercial_use: "yes",
  licence_evidence: "",
  state: "ready",
  runtime_ready: true,
  bytes_missing: 0,
  ...over,
});
vi.mock("@/lib/library", () => ({
  webModelsInUse: { inUse: async () => ({ chat: [], images: [], video: [] }) },
  webModel3d: {},
  webVoice: {
    models: async (task: string) =>
      task === "speak"
        ? [
            model({}),
            model({ id: "voxcpm2", title: "VoxCPM2", state: "can_install", bytes_missing: 4e9 }),
          ]
        : [],
  },
  webWorkers: {
    list: async () => [],
    fetchModel: (id: string) => fetchModel(id),
    fetchEngine: async () => "job-2",
    job: () => job(),
  },
}));

import { ModelsAdmin } from "./ModelsAdmin";

afterEach(cleanup);

describe("the Models page for an admin", () => {
  it("has a tab for each group the workers serve and a table of their models", async () => {
    render(<ModelsAdmin />);
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Voice", "Listening", "Music", "Lip sync"]);
    expect(screen.getByText(/models on this service's workers/i)).toBeTruthy();
    const table = await screen.findByRole("table", { name: "Voice models" });
    expect(within(table).getByText("Not on the worker")).toBeTruthy();
    expect(within(table).getByText("4.0 GB")).toBeTruthy();
  });

  it("gets a model onto the worker after saying so, then follows the job", async () => {
    const user = userEvent.setup();
    render(<ModelsAdmin />);
    await user.click(await screen.findByRole("button", { name: "Get VoxCPM2" }));
    const dialog = await screen.findByRole("dialog", { name: "Download VoxCPM2?" });
    expect(dialog.textContent).toContain("downloaded onto the worker");
    expect(fetchModel).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Get on the worker" }));
    await waitFor(() => expect(fetchModel).toHaveBeenCalledWith("voxcpm2"), { timeout: 4000 });
  });
});
