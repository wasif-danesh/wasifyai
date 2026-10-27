// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchEngine = vi.fn(async (_name: string) => "job-1");
const job = vi.fn(async () => ({ status: "done", fraction: 1, label: "", error: null }));
const list = vi.fn(async () => [worker(true)]);
vi.mock("@/lib/library", () => ({
  webWorkers: {
    list: () => list(),
    fetchEngine: (n: string) => fetchEngine(n),
    job: () => job(),
  },
}));

const worker = (ready: boolean, problem: string | null = null) => ({
  id: "mac-1",
  busy: false,
  seen: 0,
  can_fetch: true,
  models: [],
  lipsync_engine: null,
  components: { "train.video": { ready, problem, setup: { supported: true, bytes: 182_500_000 } } },
});

import { TrainersAdmin } from "./TrainersAdmin";

afterEach(() => {
  cleanup();
  fetchEngine.mockClear();
});

describe("Trainers on the Workers page", () => {
  it("says when no worker lists a trainer", () => {
    render(<TrainersAdmin workers={[]} />);
    expect(screen.getByText("No worker lists a trainer yet.")).toBeTruthy();
  });

  it("shows a ready trainer and offers to set one up, then reads the workers again", async () => {
    const user = userEvent.setup();
    render(
      <TrainersAdmin
        workers={[worker(false, "Training is not set up on the worker. Ask an admin.")]}
      />,
    );
    expect(screen.getByText(/Training is not set up on the worker/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /Set up \(183 MB\)/ }));
    expect(fetchEngine).toHaveBeenCalledWith("video-trainer");
    await waitFor(() => expect(screen.getByText("Ready")).toBeTruthy());
  });
});
