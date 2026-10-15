// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRunClient } from "@wasifyai/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { done, node, sse } from "../test-utils";
import { CreateImage } from "./CreateImage";

const fetchMock = vi.fn();
const client = createRunClient({ fetch: (path, init) => fetchMock(path, init) });

beforeEach(() => {
  fetchMock.mockReset();
  sessionStorage.clear();
});

const ready = done({
  status: "done",
  image_id: "i1",
  image_url: "http://127.0.0.1:1/files/i1.png",
  thumb_url: "http://127.0.0.1:1/files/t1.jpg",
  width: 1024,
  height: 1024,
  prompt: "a lighthouse",
  mode: "text",
});

describe("CreateImage", () => {
  it("takes a prompt, shows the progress, then the picture and the app's own actions", async () => {
    fetchMock.mockResolvedValueOnce(sse([node("check_request"), node("generate_image"), ready]));
    const user = userEvent.setup();
    render(
      <CreateImage
        client={client}
        readyNote="It's saved on this computer."
        resultActions={(r) => ({
          primary: <a href={`/download/${r.imageId}`}>Download</a>,
          more: <a href={`/library/${r.imageId}`}>Open in the library</a>,
        })}
      />,
    );

    await user.type(screen.getByRole("textbox"), "a lighthouse");
    await user.click(screen.getByRole("button", { name: /make my image/i }));

    const picture = await screen.findByRole("img", { name: "a lighthouse" });
    expect(picture).toHaveAttribute("src", "http://127.0.0.1:1/files/i1.png");
    expect(screen.getByText("It's saved on this computer.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", "/download/i1");
    expect(screen.getByRole("link", { name: /open in the library/i })).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/products/wasifyai-image/runs");

    // "Make another" brings the form back
    await user.click(screen.getByRole("button", { name: /make another/i }));
    await waitFor(() => expect(screen.getByRole("textbox")).toBeInTheDocument());
  });

  it("explains a refusal and keeps what the person wrote", async () => {
    fetchMock.mockResolvedValueOnce(
      sse([
        node("check_request"),
        done({ status: "refused", refusal: { code: "x", message: "Please try something else." } }),
      ]),
    );
    const user = userEvent.setup();
    render(<CreateImage client={client} />);
    await user.type(screen.getByRole("textbox"), "something not allowed");
    await user.click(screen.getByRole("button", { name: /make my image/i }));
    expect(await screen.findByText("Please try something else.")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("something not allowed");
  });

  it("shows a failure with Try again when the engine cannot be reached", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    const user = userEvent.setup();
    render(<CreateImage client={client} />);
    await user.type(screen.getByRole("textbox"), "a cat");
    await user.click(screen.getByRole("button", { name: /make my image/i }));
    expect(await screen.findByText(/couldn't reach the server/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
