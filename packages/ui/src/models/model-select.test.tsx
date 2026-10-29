// @vitest-environment jsdom
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { ModelSelect, type ModelSelectHandle, firstView, timeText } from "./ModelSelect";
import type { ChoiceList, ChoicesApi, ModelChoice } from "./types";

const choice = (over: Partial<ModelChoice> = {}): ModelChoice => ({
  id: "m1",
  title: "Parakeet TDT 0.6B v3",
  plain: "Turns speech into text with times; fast and accurate in English.",
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

function fake(choices: ModelChoice[], over: Partial<ChoicesApi> = {}) {
  let rows = choices;
  const api = {
    list: vi.fn(
      async (): Promise<ChoiceList> => ({
        choices: rows,
        diskFreeBytes: 500e9,
        memoryBytes: 64e9,
      }),
    ),
    choose: vi.fn(async (id: string) => {
      rows = rows.map((c) => ({ ...c, chosen: c.id === id }));
    }),
    get: vi.fn(async (id: string, on: (p: { label: string; fraction: number | null }) => void) => {
      on({ label: "Getting the model", fraction: 0.4 });
      rows = rows.map((c) =>
        c.id === id ? { ...c, state: "ready" as const, chosen: true } : { ...c, chosen: false },
      );
    }),
    ...over,
  } satisfies ChoicesApi;
  return api;
}

describe("the model picker button and panel", () => {
  it("says what to select when nothing is chosen, and names the model in use otherwise", async () => {
    const none = fake([choice()]);
    const { unmount } = render(<ModelSelect group="listening" api={none} />);
    expect(
      await screen.findByRole("button", { name: /Select transcription model/ }),
    ).toBeInTheDocument();
    unmount();
    render(
      <ModelSelect group="listening" api={fake([choice({ state: "ready", chosen: true })])} />,
    );
    expect(await screen.findByRole("button", { name: /Parakeet TDT 0.6B v3/ })).toBeInTheDocument();
  });

  it("opens on the recommended models, at most three, the best fit first, and not the advanced ones", async () => {
    const rows = [
      choice({
        id: "a",
        title: "A big one",
        fit: "too_big",
        state: "too_big",
        tier: "recommended",
      }),
      choice({ id: "b", title: "B", fit: "tight", tier: "also" }),
      choice({ id: "c", title: "C", fit: "fits", tier: "also" }),
      choice({ id: "d", title: "D", fit: "fits", tier: "recommended" }),
      choice({ id: "e", title: "E (advanced)", tier: "advanced" }),
    ];
    expect(firstView(rows).map((c) => c.id)).toEqual(["d", "c", "b"]);
    const user = userEvent.setup();
    render(<ModelSelect group="images" api={fake(rows)} />);
    await user.click(await screen.findByRole("button", { name: /Select image model/ }));
    const list = await screen.findByRole("list", { name: "Models" });
    expect(within(list).getAllByRole("button")).toHaveLength(3);
    expect(within(list).queryByText("E (advanced)")).toBeNull();
    // the advanced one is under More
    await user.click(screen.getByRole("tab", { name: "More" }));
    expect(screen.getByText("E (advanced)")).toBeInTheDocument();
  });

  it("uses a model that is on the computer, at once, and closes", async () => {
    const api = fake([choice({ state: "ready" })]);
    const changed = vi.fn();
    const user = userEvent.setup();
    render(<ModelSelect group="listening" api={api} onChanged={changed} />);
    await user.click(await screen.findByRole("button", { name: /Select transcription model/ }));
    await user.click(await screen.findByRole("button", { name: /Parakeet TDT 0.6B v3/ }));
    expect(api.choose).toHaveBeenCalledWith("m1");
    expect(changed).toHaveBeenCalledWith("m1");
    await waitFor(() => expect(screen.queryByRole("region", { name: /Select/ })).toBeNull());
    expect(screen.getByRole("button", { name: /Parakeet TDT 0.6B v3/ })).toBeInTheDocument();
  });

  it("lists what is on the computer under its own tab, and opens there when there is something", async () => {
    const user = userEvent.setup();
    render(
      <ModelSelect
        group="voice"
        api={fake([
          choice({ id: "x", title: "On disk", state: "ready" }),
          choice({ id: "y", title: "Not yet" }),
        ])}
      />,
    );
    await user.click(await screen.findByRole("button", { name: /Select voice model/ }));
    expect(
      await screen.findByRole("tab", { name: "On this computer", selected: true }),
    ).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "On this computer" });
    expect(within(list).getByText("On disk")).toBeInTheDocument();
    expect(within(list).queryByText("Not yet")).toBeNull();
  });

  it("cannot choose a model that is too big, and says why", async () => {
    const user = userEvent.setup();
    render(
      <ModelSelect group="video" api={fake([choice({ state: "too_big", fit: "too_big" })])} />,
    );
    await user.click(await screen.findByRole("button", { name: /Select video model/ }));
    const row = await screen.findByRole("button", { name: /Parakeet TDT 0.6B v3/ });
    expect(row).toBeDisabled();
    expect(within(row).getByText(/Too big for this computer/)).toBeInTheDocument();
  });

  it("can be opened by the screen, for the main button pressed with no model", async () => {
    const handle = createRef<ModelSelectHandle>();
    render(<ModelSelect group="music" api={fake([choice()])} handleRef={handle} />);
    await screen.findByRole("button", { name: /Select music model/ });
    act(() => handle.current?.open());
    expect(await screen.findByRole("dialog", { name: /Select music model/ })).toBeInTheDocument();
  });
});

describe("choosing a model that is not on the computer", () => {
  it("asks first, in words, with the engine and the model and the total, and downloads only on a yes", async () => {
    const api = fake([
      choice({
        id: "f",
        title: "FLUX.2 klein 4B",
        downloadBytes: 16.1e9,
        engineBytes: 1.5e9,
        engineName: "The image engine",
        plain: "Makes and edits pictures.",
      }),
    ]);
    const changed = vi.fn();
    const user = userEvent.setup();
    render(<ModelSelect group="images" api={api} onChanged={changed} />);
    await user.click(await screen.findByRole("button", { name: /Select image model/ }));
    await user.click(await screen.findByRole("button", { name: /FLUX.2 klein 4B/ }));
    const dialog = await screen.findByRole("dialog", { name: "Download FLUX.2 klein 4B?" });
    expect(within(dialog).getByText(/we need to download it first/)).toBeInTheDocument();
    expect(within(dialog).getByText("The image engine (once)")).toBeInTheDocument();
    expect(within(dialog).getByText("1.5 GB")).toBeInTheDocument();
    expect(within(dialog).getByText("16 GB")).toBeInTheDocument();
    expect(within(dialog).getByText(/18 GB, about \d+ minutes/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/commercial|licence/i)).toBeNull();
    expect(api.get).not.toHaveBeenCalled(); // nothing yet
    await user.click(within(dialog).getByRole("button", { name: "Not now" }));
    // the question closes; the picker, a dialog of its own since stage U3, stays open
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Download FLUX.2 klein 4B?" })).toBeNull();

    await user.click(screen.getByRole("button", { name: /FLUX.2 klein 4B/ }));
    await user.click(screen.getByRole("button", { name: "Download and use" }));
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("f", expect.any(Function), expect.any(AbortSignal)),
    );
    await waitFor(() => expect(changed).toHaveBeenCalledWith("f"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull()); // done: it is chosen and the box closes
    expect(screen.getByRole("button", { name: /FLUX.2 klein 4B/ })).toBeInTheDocument();
  });

  it("will not start when the disk is too full, and says so before asking", async () => {
    const api = fake([choice({ downloadBytes: 16e9 })]);
    vi.mocked(api.list).mockResolvedValue({
      choices: [choice({ downloadBytes: 16e9 })],
      diskFreeBytes: 5e9,
      memoryBytes: 64e9,
    });
    const user = userEvent.setup();
    render(<ModelSelect group="listening" api={api} />);
    await user.click(await screen.findByRole("button", { name: /Select transcription model/ }));
    await user.click(await screen.findByRole("button", { name: /Parakeet TDT 0.6B v3/ }));
    expect(await screen.findByText(/not enough free disk space: 5.0 GB free/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download and use" })).toBeDisabled();
  });

  it("gives a plain time for a download", () => {
    expect(timeText(10_000_000)).toBe("about a minute");
    expect(timeText(916_000_000)).toBe("about 2 minutes");
    expect(timeText(40e9)).toBe("over an hour");
  });
});
