// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRunClient } from "@wasifyai/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ImageForm } from "./ImageForm";

const fetchMock = vi.fn();
const client = createRunClient({ fetch: (path, init) => fetchMock(path, init) });
beforeEach(() => {
  fetchMock.mockReset();
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

const png = (bytes = 10, type = "image/png") =>
  new File([new Uint8Array(bytes)], "a.png", { type });

describe("ImageForm", () => {
  it("makes a text image with the chosen shape", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<ImageForm client={client} onSubmit={onSubmit} />);
    const go = screen.getByRole("button", { name: /make my image/i });
    expect(go).toBeDisabled();
    await user.type(screen.getByRole("textbox"), "  a lighthouse ");
    await user.click(screen.getByRole("button", { name: /wide/i }));
    await user.click(go);
    expect(onSubmit).toHaveBeenCalledWith({
      mode: "text",
      prompt: "a lighthouse",
      size: "wide",
      picture: null,
    });
  });

  it("needs a picture in picture mode, uploads it at once, and hands it to the run", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({ upload_id: "u1", key: "uploads/u1.png", width: 300, height: 200, bytes: 9 }),
    );
    const onSubmit = vi.fn();
    const user = userEvent.setup({ applyAccept: false });
    render(<ImageForm client={client} onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: /from a picture/i }));
    await user.type(screen.getByRole("textbox"), "make it blue");
    const go = screen.getByRole("button", { name: /make my image/i });
    expect(go).toBeDisabled();
    expect(screen.getByText(/deleted once it has been used/i)).toBeInTheDocument();

    await user.upload(screen.getByLabelText("Your picture"), png());
    await waitFor(() => expect(go).toBeEnabled());
    expect(fetchMock.mock.calls[0][0]).toBe("/products/wasifyai-image/uploads/images");
    await user.click(go);
    const value = onSubmit.mock.calls[0][0];
    expect(value).toMatchObject({ mode: "image", prompt: "make it blue", size: "square" });
    expect(value.picture).toMatchObject({ uploadId: "u1", key: "uploads/u1.png" });
  });

  it("refuses a bad file in the browser without uploading it", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<ImageForm client={client} onSubmit={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /from a picture/i }));
    await user.upload(
      screen.getByLabelText("Your picture"),
      new File(["x"], "a.gif", { type: "image/gif" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/PNG, JPEG or WebP/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("switches to the picture mode when a picture is pasted, and ignores a text paste", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({ upload_id: "u2", key: "uploads/u2.png", width: 3, height: 2, bytes: 9 }),
    );
    render(<ImageForm client={client} onSubmit={vi.fn()} />);
    const file = png();
    const paste = (types: string[], withFile: boolean) => {
      const e = new Event("paste", { bubbles: true, cancelable: true }) as Event & {
        clipboardData: unknown;
      };
      e.clipboardData = {
        types,
        items: withFile ? [{ kind: "file", getAsFile: () => file }] : [],
        files: withFile ? [file] : [],
      };
      document.dispatchEvent(e);
      return e;
    };
    expect(paste(["text/plain"], false).defaultPrevented).toBe(false);
    expect(paste(["text/plain", "Files"], true).defaultPrevented).toBe(false); // a spreadsheet copy
    expect(fetchMock).not.toHaveBeenCalled();
    expect(paste(["Files"], true).defaultPrevented).toBe(true);
    await waitFor(() => expect(screen.getByAltText(/preview of your upload/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /from a picture/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("accepts a dropped picture and takes it back from the server when removed", async () => {
    fetchMock
      .mockResolvedValueOnce(
        Response.json({ upload_id: "u3", key: "uploads/u3.png", width: 3, height: 2, bytes: 9 }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const user = userEvent.setup();
    render(<ImageForm client={client} onSubmit={vi.fn()} />);
    const file = png();
    const drop = new Event("drop", { bubbles: true, cancelable: true }) as Event & {
      dataTransfer: unknown;
    };
    drop.dataTransfer = {
      types: ["Files"],
      items: [{ kind: "file", getAsFile: () => file }],
      files: [file],
    };
    window.dispatchEvent(drop);
    expect(drop.defaultPrevented).toBe(true); // the browser must not open the file
    await waitFor(() => expect(screen.getByAltText(/preview of your upload/i)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /remove/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe("/products/wasifyai-image/uploads/images/u3");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "DELETE" });
    expect(screen.getByRole("button", { name: /choose a picture/i })).toBeInTheDocument();
  });
});
