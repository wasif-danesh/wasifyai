// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { NotebookOutput, NotebooksApi } from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { type SaveAs, SaveAsProvider } from "../save";
import { StudioPane } from "./StudioPane";
import { NotebookPlaceProvider } from "./place";
import { useStudioWidth } from "./use-studio-width";

const output = (over: Partial<NotebookOutput> = {}): NotebookOutput => ({
  id: "o1",
  notebook_id: "n1",
  format: "word",
  title: "Launch plan",
  status: "ready",
  error: null,
  prompt: "",
  source_ids: [],
  has_file: true,
  file_name: "launch-plan.docx",
  file_mime: "application/octet-stream",
  created_at: "2026-10-16T00:00:00Z",
  updated_at: "2026-10-16T00:00:00Z",
  ...over,
});

function setup(
  opts: {
    list?: NotebookOutput[];
    place?: "device" | "hosted";
    saveImage?: (id: string, path?: string) => Promise<{ name: string; path?: string }>;
    exportFails?: boolean;
    dialog?: SaveAs;
  } = {},
) {
  const list = opts.list ?? [output()];
  const api = {
    outputs: vi.fn(async () => [...list]),
    output: vi.fn(async (_n: string, id: string) => ({
      ...(list.find((o) => o.id === id) as NotebookOutput),
      body: "",
      data: list.find((o) => o.id === id)?.data ?? null,
    })),
    renameOutput: vi.fn(async () => {}),
    removeOutput: vi.fn(async () => {}),
    cancelOutput: vi.fn(async () => {}),
    outputFile: vi.fn(async () => new Blob(["x"])),
    exportOutput: vi.fn(async (_n: string, _o: string, path?: string) => {
      if (opts.exportFails) throw new Error("gone");
      return { name: "launch-plan.docx", path: path ?? "/Users/me/Downloads/launch-plan.docx" };
    }),
  } as unknown as NotebooksApi;
  render(
    <SaveAsProvider value={opts.dialog ?? null}>
      <NotebookPlaceProvider place={opts.place ?? "device"}>
        <StudioPane
          api={api}
          runs={{ startRun: vi.fn() }}
          notebookId="n1"
          scopeLabel="3 sources"
          saveImage={opts.saveImage}
          imageUrl={async () => "http://127.0.0.1:1/files/img.png"}
        />
      </NotebookPlaceProvider>
    </SaveAsProvider>,
  );
  return api;
}

beforeEach(() => {
  // the app window has neither of these: they must never be needed
  vi.stubGlobal("confirm", () => {
    throw new Error("window.confirm is not available in the app window");
  });
  vi.stubGlobal("prompt", () => {
    throw new Error("window.prompt is not available in the app window");
  });
});

describe("the cards of the outputs", () => {
  it("renames in a box of the page and keeps the name, with the pencil saying what it does", async () => {
    const user = userEvent.setup();
    const api = setup();
    const pencil = await screen.findByRole("button", { name: "Rename Launch plan" });
    expect(pencil).toHaveAttribute("title", "Rename");
    await user.click(pencil);
    const box = screen.getByRole("dialog", { name: "Rename this output" });
    const field = within(box).getByLabelText("Name");
    expect(field).toHaveValue("Launch plan");
    await user.clear(field);
    await user.type(field, "Q3 plan{Enter}");
    expect(api.renameOutput).toHaveBeenCalledWith("n1", "o1", "Q3 plan");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("does nothing when the name is left as it was or the box is cancelled", async () => {
    const user = userEvent.setup();
    const api = setup();
    await user.click(await screen.findByRole("button", { name: "Rename Launch plan" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(api.renameOutput).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Rename Launch plan" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.renameOutput).not.toHaveBeenCalled();
  });

  it("asks before deleting, in a box of the page, and deletes only on the button", async () => {
    const user = userEvent.setup();
    const api = setup();
    await user.click(await screen.findByRole("button", { name: "Delete Launch plan" }));
    const box = screen.getByRole("dialog", { name: "Delete this output?" });
    expect(within(box).getByText(/“Launch plan” will be deleted/)).toBeInTheDocument();
    await user.click(within(box).getByRole("button", { name: "Cancel" }));
    expect(api.removeOutput).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Delete Launch plan" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(api.removeOutput).toHaveBeenCalledWith("n1", "o1");
  });

  it("saves a copy into the folder in the app window and says where it went", async () => {
    const user = userEvent.setup();
    const api = setup();
    await user.click(await screen.findByRole("button", { name: "Save launch-plan.docx" }));
    expect(api.exportOutput).toHaveBeenCalledWith("n1", "o1", undefined);
    expect(api.outputFile).not.toHaveBeenCalled();
    expect(await screen.findByText("Saved as launch-plan.docx in Downloads.")).toBeInTheDocument();
  });

  it("shows the message above the cards, where it is seen, and saves one copy per click", async () => {
    const user = userEvent.setup();
    const api = setup();
    vi.mocked(api.exportOutput).mockImplementation(
      () =>
        new Promise((done) =>
          setTimeout(() => done({ name: "launch-plan.docx", path: "/Users/me/Downloads/x" }), 80),
        ),
    ); // a copy takes a moment
    const save = await screen.findByRole("button", { name: "Save launch-plan.docx" });
    await user.dblClick(save); // a second click while it is saving does not make a second copy
    const said = await screen.findByText("Saved as launch-plan.docx in Downloads.");
    expect(api.exportOutput).toHaveBeenCalledTimes(1);
    const header = screen.getByRole("heading", { name: "Studio" });
    expect(header.compareDocumentPosition(said) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const [tiles] = screen.getAllByRole("list");
    expect(tiles?.compareDocumentPosition(said)).toBe(Node.DOCUMENT_POSITION_PRECEDING); // above the tiles and the outputs
  });

  it("says in words when a copy could not be saved", async () => {
    const user = userEvent.setup();
    setup({ exportFails: true });
    await user.click(await screen.findByRole("button", { name: "Save launch-plan.docx" }));
    expect(await screen.findByText(/could not be saved/i)).toBeInTheDocument();
  });

  it("lets the browser save it on the web", async () => {
    const user = userEvent.setup();
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const api = setup({ place: "hosted" });
    await user.click(await screen.findByRole("button", { name: "Save launch-plan.docx" }));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(api.outputFile).toHaveBeenCalledWith("n1", "o1");
    expect(api.exportOutput).not.toHaveBeenCalled();
    click.mockRestore();
  });

  it("offers to save the picture of an infographic, which has no file of its own", async () => {
    const user = userEvent.setup();
    const saveImage = vi.fn(async (_id: string, path?: string) => ({
      name: "launch.png",
      path: path ?? "/Users/me/Downloads/launch.png",
    }));
    setup({
      list: [
        output({
          id: "i1",
          format: "infographic",
          title: "Launch",
          has_file: false,
          file_name: null,
          data: {
            title: "Launch",
            summary: "",
            image_id: "img-1",
            sections: [{ label: "Budget", value: "$1", detail: "" }],
          },
        }),
      ],
      saveImage,
    });
    // the card saves the picture without opening it
    await user.click(await screen.findByRole("button", { name: "Save the picture of Launch" }));
    expect(saveImage).toHaveBeenCalledWith("img-1", undefined);
    expect(await screen.findByText("Saved as launch.png in Downloads.")).toBeInTheDocument();
    // and so does the open output
    saveImage.mockClear();
    await user.click(screen.getByRole("button", { name: "Launch" }));
    await user.click(await screen.findByRole("button", { name: "Save the picture" }));
    expect(saveImage).toHaveBeenCalledWith("img-1", undefined);
  });
});

describe("the Save As box of the app window", () => {
  it("asks where to save, with the file's name, and the engine writes it there", async () => {
    const user = userEvent.setup();
    const choose = vi.fn(async () => "/Users/me/Documents/Q3 plan.docx");
    const api = setup({ dialog: { choose, write: vi.fn() } });
    await user.click(await screen.findByRole("button", { name: "Save launch-plan.docx" }));
    expect(choose).toHaveBeenCalledWith("launch-plan.docx");
    expect(api.exportOutput).toHaveBeenCalledWith("n1", "o1", "/Users/me/Documents/Q3 plan.docx");
    expect(await screen.findByText("Saved as launch-plan.docx in Documents.")).toBeInTheDocument();
  });

  it("saves nothing, and says nothing, when the person cancels", async () => {
    const user = userEvent.setup();
    const api = setup({ dialog: { choose: async () => null, write: vi.fn() } });
    await user.click(await screen.findByRole("button", { name: "Save launch-plan.docx" }));
    await new Promise((r) => setTimeout(r, 20));
    expect(api.exportOutput).not.toHaveBeenCalled();
    expect(screen.queryByText(/Saved as|could not be saved/)).toBeNull();
  });

  it("saves the picture of an infographic at the chosen path through the image's own export", async () => {
    const user = userEvent.setup();
    const saveImage = vi.fn(async (_id: string, path?: string) => ({ name: "x.png", path }));
    setup({
      dialog: { choose: async () => "/Users/me/Pictures/launch facts.png", write: vi.fn() },
      saveImage,
      list: [
        output({
          id: "i1",
          format: "infographic",
          title: "Launch facts",
          has_file: false,
          file_name: null,
          data: {
            title: "Launch facts",
            summary: "",
            image_id: "img-1",
            sections: [{ label: "Budget", value: "$1", detail: "" }],
          },
        }),
      ],
    });
    await user.click(
      await screen.findByRole("button", { name: "Save the picture of Launch facts" }),
    );
    expect(saveImage).toHaveBeenCalledWith("img-1", "/Users/me/Pictures/launch facts.png");
    expect(await screen.findByText("Saved as x.png in Pictures.")).toBeInTheDocument();
  });
});

function Harness() {
  const w = useStudioWidth();
  return (
    <div ref={w.grid} style={{ width: 1600 }}>
      <div ref={w.column} data-testid="column">
        <div
          role="separator"
          aria-label="Resize the Studio"
          tabIndex={0}
          aria-valuenow={w.width ?? undefined}
          {...w.handle}
        />
        <button type="button" onClick={w.toggleWide}>
          wide:{String(w.wide)}
        </button>
        <output>{w.width === null ? "default" : w.width}</output>
      </div>
    </div>
  );
}

describe("the width of the Studio", () => {
  beforeEach(() => localStorage.clear());

  it("grows and shrinks with the arrow keys, goes back with Home, and is remembered", async () => {
    const user = userEvent.setup();
    const first = render(<Harness />);
    const handle = screen.getByRole("separator");
    handle.focus();
    // jsdom has no layout: the pane measures as its minimum
    await user.keyboard("{ArrowLeft}");
    expect(first.container.querySelector("output")?.textContent).toBe("296");
    expect(localStorage.getItem("wasifyai:studio-width")).toBe("296");
    first.unmount();
    const again = render(<Harness />); // a new visit starts where the last one ended
    expect(again.container.querySelector("output")?.textContent).toBe("296");
    screen.getByRole("separator").focus();
    await user.keyboard("{Home}");
    expect(again.container.querySelector("output")?.textContent).toBe("default");
    expect(localStorage.getItem("wasifyai:studio-width")).toBeNull();
  });

  it("follows a drag, never past its limits, and widens with a double-click", () => {
    render(<Harness />);
    const column = screen.getByTestId("column");
    column.getBoundingClientRect = () => ({ right: 1600, width: 300 }) as DOMRect;
    const handle = screen.getByRole("separator");
    handle.setPointerCapture = vi.fn();
    handle.releasePointerCapture = vi.fn();
    handle.hasPointerCapture = vi.fn(() => true);
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 1300 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 1000 }); // 600 wide
    expect(screen.getByRole("status").textContent).toBe("600");
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 1590 }); // too narrow: the minimum
    expect(screen.getByRole("status").textContent).toBe("272");
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 0 }); // too wide: what the others keep
    expect(Number(screen.getByRole("status").textContent)).toBeLessThanOrEqual(960);
    fireEvent.pointerUp(handle, { pointerId: 1 });
    fireEvent.doubleClick(handle); // from wide back to the default
    expect(screen.getByRole("status").textContent).toBe("default");
    fireEvent.doubleClick(handle);
    expect(screen.getByRole("status").textContent).toBe("640");
  });
});
