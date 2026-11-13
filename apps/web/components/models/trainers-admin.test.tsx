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
    expect(screen.getByText("No worker lists a trainer or tool yet.")).toBeTruthy();
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

  it("offers to set song analysis up on a worker that lists it", async () => {
    const user = userEvent.setup();
    const analysis = {
      ...worker(false),
      components: {
        music_analysis: {
          ready: false,
          problem: null,
          setup: { supported: true, bytes: 970_000_000 },
        },
      },
    };
    render(<TrainersAdmin workers={[analysis]} />);
    expect(screen.getByText("Song analysis")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /Set up \(970 MB\)/ }));
    expect(fetchEngine).toHaveBeenCalledWith("music-analysis");
  });
});
