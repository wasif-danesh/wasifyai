import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
// @vitest-environment jsdom
import type { TrainBase, TrainHubState } from "@wasifyai/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HubFetch } from "./HubFetch";

const base: TrainBase = {
  id: "flux3-image-klein",
  title: "FLUX.3 Image Klein",
  engine: "ai-toolkit",
  recommended: false,
  can_teach: true,
  reason: "",
  installed: false,
  fetch_bytes: 20e9,
  methods: [],
};

afterEach(cleanup);

describe("HubFetch", () => {
  it("offers the training files with their size and gets them after a click", async () => {
    let state: TrainHubState = { state: "idle" };
    const api = {
      hubState: vi.fn(async () => state),
      fetchHub: vi.fn(async (_b: string, bytes: number) => {
        state = {
          state: "fetching",
          base: base.id,
          bytes_total: bytes,
          bytes_start: 0,
          bytes_done: 5e9,
        };
        return state;
      }),
      cancelHub: vi.fn(async () => ({ state: "idle" }) as TrainHubState),
    };
    render(<HubFetch api={api} base={base} onDone={() => {}} />);
    const get = await screen.findByRole("button", { name: "Get its training files (20 GB)" });
    await act(async () => fireEvent.click(get));
    expect(api.fetchHub).toHaveBeenCalledWith("flux3-image-klein", 20e9);
    expect(await screen.findByText("5.0 GB of 20 GB")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy();
  });

  it("shows nothing for a model with nothing to fetch, or one that cannot be taught here", () => {
    const api = {
      hubState: vi.fn(async () => ({ state: "idle" }) as TrainHubState),
      fetchHub: vi.fn(),
    };
    const { container, rerender } = render(
      <HubFetch api={api} base={{ ...base, fetch_bytes: 0 }} onDone={() => {}} />,
    );
    expect(container.textContent).toBe("");
    rerender(<HubFetch api={api} base={{ ...base, can_teach: false }} onDone={() => {}} />);
    expect(container.textContent).toBe("");
  });
});
