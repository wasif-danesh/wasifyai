// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ModelSelect } from "./ModelSelect";
import { ModelChoicesProvider } from "./context";
import type { ChoiceList, ChoicesApi, GetProgress, ModelChoice } from "./types";

const choice = (over: Partial<ModelChoice> = {}): ModelChoice => ({
  id: "m1",
  title: "Parakeet TDT 0.6B v3",
  plain: "Turns speech into text.",
  tier: "recommended",
  state: "needs_download",
  chosen: false,
  downloadBytes: 916_000_000,
  engineBytes: 0,
  engineName: null,
  fit: "fits",
  fitReason: null,
  source: "app",
  ...over,
});

/** An engine whose downloads wait until the test lets them end: `finish`, or `fail`. */
function slowApi(rows: ModelChoice[]) {
  const ends = new Map<string, { finish: () => void; fail: (e: Error) => void }>();
  let current = rows;
  const api = {
    list: vi.fn(
      async (): Promise<ChoiceList> => ({
        choices: current,
        diskFreeBytes: 500e9,
        memoryBytes: 64e9,
      }),
    ),
    choose: vi.fn(async () => {}),
    get: vi.fn(
      (id: string, on: (p: GetProgress) => void, signal: AbortSignal) =>
        new Promise<void>((resolve, reject) => {
          on({ label: "Getting the model", fraction: 0.4 });
          ends.set(id, {
            finish: () => {
              current = current.map((c) =>
                c.id === id ? { ...c, state: "ready" as const, chosen: true } : c,
              );
              resolve();
            },
            fail: reject,
          });
          signal.addEventListener("abort", () => reject(new Error("stopped")));
        }),
    ),
  } satisfies ChoicesApi;
  return { api, ends };
}

function Screen({ api, shown = true }: { api: ChoicesApi; shown?: boolean }) {
  return (
    <ModelChoicesProvider source={() => api}>
      <button type="button">Another menu item</button>
      {shown ? <ModelSelect group="listening" api={api} /> : null}
    </ModelChoicesProvider>
  );
}

async function startDownload(user: ReturnType<typeof userEvent.setup>, name = /Parakeet/) {
  await user.click(await screen.findByRole("button", { name: /Select transcription model/ }));
  await user.click(await screen.findByRole("button", { name }));
  await user.click(await screen.findByRole("button", { name: "Download and use" }));
}

describe("a download does not block the window", () => {
  it("closes the dialog at once and shows the progress in a tray; the rest of the app stays usable", async () => {
    const { api } = slowApi([choice()]);
    const user = userEvent.setup();
    render(<Screen api={api} />);
    await startDownload(user);
    expect(screen.queryByRole("dialog")).toBeNull(); // nothing covers the page
    const tray = await screen.findByRole("region", { name: "Downloads" });
    expect(within(tray).getByText("Download in progress")).toBeInTheDocument();
    expect(within(tray).getByText("Parakeet TDT 0.6B v3")).toBeInTheDocument();
    expect(within(tray).getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("Downloading 40%")).toBeInTheDocument(); // on the model button too
    await user.click(screen.getByRole("button", { name: "Another menu item" })); // not inert
  });

  it("goes on when the screen that asked is gone, and says when the model is ready", async () => {
    const { api, ends } = slowApi([choice()]);
    const user = userEvent.setup();
    const { rerender } = render(<Screen api={api} />);
    await startDownload(user);
    rerender(<Screen api={api} shown={false} />); // the person went to another screen
    const tray = await screen.findByRole("region", { name: "Downloads" });
    expect(within(tray).getByText("40%")).toBeInTheDocument();
    await act(async () => ends.get("m1")?.finish());
    expect(await within(tray).findByText("Ready")).toBeInTheDocument();
  });

  it("can be stopped from the tray, and the row goes away", async () => {
    const { api } = slowApi([choice()]);
    const user = userEvent.setup();
    render(<Screen api={api} />);
    await startDownload(user);
    await user.click(
      await screen.findByRole("button", { name: "Stop downloading Parakeet TDT 0.6B v3" }),
    );
    await waitFor(() => expect(screen.queryByRole("region", { name: "Downloads" })).toBeNull());
    expect(api.get.mock.calls[0]?.[2].aborted).toBe(true);
  });

  it("says in words when it failed and offers to try again", async () => {
    const { api, ends } = slowApi([choice()]);
    const user = userEvent.setup();
    render(<Screen api={api} />);
    await startDownload(user);
    await act(async () =>
      ends
        .get("m1")
        ?.fail(new Error("There is not enough free disk space: 4 GB free, 17 GB needed.")),
    );
    expect(await screen.findByText(/not enough free disk space/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  });

  it("downloads one at a time, in the order asked", async () => {
    const { api, ends } = slowApi([
      choice(),
      choice({ id: "m2", title: "Second model", downloadBytes: 1e9 }),
    ]);
    const user = userEvent.setup();
    function Two() {
      const [n] = useState(0);
      return (
        <ModelChoicesProvider source={() => api}>
          <ModelSelect group="listening" api={api} key={n} />
        </ModelChoicesProvider>
      );
    }
    render(<Two />);
    await startDownload(user);
    await startDownload(user, /Second model/);
    const tray = await screen.findByRole("region", { name: "Downloads" });
    expect(within(tray).getByText("Waiting")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledTimes(1); // the second has not started
    await act(async () => ends.get("m1")?.finish());
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  });
});
