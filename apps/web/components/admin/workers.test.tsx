// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { WorkerInfo, WorkerModel, WorkersApi } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { WorkersPanel } from "./WorkersPanel";

const model = (over: Partial<WorkerModel>): WorkerModel => ({
  id: "kokoro-82m",
  title: "Kokoro",
  state: "ready",
  bytes_missing: 0,
  licence: "Apache-2.0",
  commercial_use: "yes",
  tasks: ["speak"],
  engine: "audio.cpp",
  runtime_ready: true,
  ...over,
});

const worker = (
  models: WorkerModel[],
  lipsync: WorkerInfo["lipsync_engine"] = null,
): WorkerInfo => ({
  id: "mac",
  busy: false,
  seen: 0,
  can_fetch: true,
  models,
  lipsync_engine: lipsync,
  components: {},
});

function api(over: Partial<WorkersApi> = {}): WorkersApi {
  return {
    list: vi.fn(async () => []),
    fetchModel: vi.fn(async () => "job-1"),
    fetchEngine: vi.fn(async () => "job-2"),
    job: vi.fn(async () => ({
      status: "working",
      fraction: 0.4,
      label: "Downloading m.bin",
      error: null,
    })),
    ...over,
  };
}

describe("the Workers page", () => {
  it("says what to do when no worker is running", () => {
    render(<WorkersPanel initial={[]} api={api()} />);
    expect(screen.getByText(/No worker is running/)).toBeTruthy();
  });

  it("shows what a worker has and offers the rest with its size", () => {
    const initial = [
      worker([
        model({}),
        model({ id: "voxcpm2", title: "VoxCPM2", state: "can_install", bytes_missing: 4e9 }),
      ]),
    ];
    render(<WorkersPanel initial={initial} api={api()} />);
    expect(screen.getByText("Yes")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Get VoxCPM2 \(4\.0 GB\)/ })).toBeTruthy();
  });

  it("starts a fetch, follows it, and reads the workers again when it ends", async () => {
    const calls = api();
    const listed = [worker([model({ id: "voxcpm2", title: "VoxCPM2" })])];
    calls.list = vi.fn(async () => listed);
    calls.job = vi
      .fn()
      .mockResolvedValueOnce({
        status: "working",
        fraction: 0.4,
        label: "Downloading m.bin",
        error: null,
      })
      .mockResolvedValue({ status: "done", fraction: 1, label: "", error: null });
    const initial = [
      worker([
        model({ id: "voxcpm2", title: "VoxCPM2", state: "can_install", bytes_missing: 4e9 }),
      ]),
    ];
    render(<WorkersPanel initial={initial} api={calls} />);
    await userEvent.click(screen.getByRole("button", { name: /Get VoxCPM2/ }));
    expect(calls.fetchModel).toHaveBeenCalledWith("voxcpm2");
    await waitFor(() => expect(screen.getByText(/Downloading m.bin · 40%/)).toBeTruthy(), {
      timeout: 4000,
    });
    await waitFor(() => expect(calls.list).toHaveBeenCalled(), { timeout: 6000 });
    await waitFor(() => expect(screen.getByText("Yes")).toBeTruthy());
  }, 15000);

  it("shows why a fetch could not start", async () => {
    const calls = api({
      fetchModel: vi.fn(async () =>
        Promise.reject(new Error("No worker is running that can fetch models.")),
      ),
    });
    const initial = [
      worker([
        model({ id: "voxcpm2", title: "VoxCPM2", state: "can_install", bytes_missing: 4e9 }),
      ]),
    ];
    render(<WorkersPanel initial={initial} api={calls} />);
    await userEvent.click(screen.getByRole("button", { name: /Get VoxCPM2/ }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/No worker is running/);
  });

  it("sets up the lip sync engine from the page", async () => {
    const calls = api();
    const initial = [worker([], { installed: false, supported: true, bytes: 9e8 })];
    render(<WorkersPanel initial={initial} api={calls} />);
    await userEvent.click(screen.getByRole("button", { name: /Set up the lip sync engine/ }));
    expect(calls.fetchEngine).toHaveBeenCalledWith("lipsync-engine");
  });
});
