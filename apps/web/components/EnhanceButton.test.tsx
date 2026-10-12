// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EnhanceButton } from "./EnhanceButton";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function Harness(props: { start?: string; needsPicture?: boolean; uploadId?: string }) {
  const [value, setValue] = useState(props.start ?? "a fox");
  return (
    <>
      <output aria-label="text">{value}</output>
      <EnhanceButton
        product="wasifyai-image"
        kind="text_to_image"
        value={value}
        needsPicture={props.needsPicture}
        uploadId={props.uploadId}
        maxChars={50}
        onChange={setValue}
      />
    </>
  );
}

describe("EnhanceButton", () => {
  it("rewrites the text, sends the kind and the picture, and Undo brings the original back", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ prompt: "A red fox in snow.", changed: true }));
    const user = userEvent.setup();
    render(<Harness uploadId="u1" />);
    await user.click(screen.getByRole("button", { name: /enhance/i }));
    await waitFor(() =>
      expect(screen.getByLabelText("text")).toHaveTextContent("A red fox in snow."),
    );
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/products/wasifyai-image/prompt/enhance");
    expect(JSON.parse(init.body as string)).toEqual({
      kind: "text_to_image",
      prompt: "a fox",
      upload_id: "u1",
    });
    await user.click(screen.getByRole("button", { name: /undo/i }));
    expect(screen.getByLabelText("text")).toHaveTextContent("a fox");
    expect(screen.queryByRole("button", { name: /undo/i })).toBeNull();
  });

  it("leaves the text alone when it already looks good", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ prompt: "a fox", changed: false }));
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /enhance/i }));
    await waitFor(() => expect(screen.getByText(/already looks good/i)).toBeInTheDocument());
    expect(screen.getByLabelText("text")).toHaveTextContent("a fox");
    expect(screen.queryByRole("button", { name: /undo/i })).toBeNull();
  });

  it("shows the server's plain message when it is refused or busy, and keeps the text", async () => {
    fetchMock.mockResolvedValueOnce(
      Response.json({ detail: "I can't help with that request." }, { status: 422 }),
    );
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /enhance/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("I can't help with that request.");
    expect(screen.getByLabelText("text")).toHaveTextContent("a fox");
    expect(screen.getByRole("button", { name: /enhance/i })).toBeEnabled(); // can try again
  });

  it("is disabled for empty or too long text and until a picture is there when one is needed", () => {
    const { rerender } = render(<Harness start="   " />);
    expect(screen.getByRole("button", { name: /enhance/i })).toBeDisabled();
    rerender(<Harness start={"x".repeat(51)} />);
    expect(screen.getByRole("button", { name: /enhance/i })).toBeDisabled();
  });

  it("waits for the picture in a picture mode", () => {
    render(<Harness needsPicture />);
    expect(screen.getByRole("button", { name: /enhance/i })).toBeDisabled();
  });
});
