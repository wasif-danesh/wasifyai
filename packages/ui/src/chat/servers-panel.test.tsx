// @vitest-environment jsdom
// The box's panel for outside servers (ADR-0070 decision 10, stage C3): a resource is attached as a document, a
// prompt with an argument is filled in and put in the box.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { type ExternalControl, ServersPanel } from "./servers-panel";

function control(): ExternalControl {
  return {
    servers: vi.fn(async () => [{ id: "s1", name: "notes" }]),
    resources: vi.fn(async () => [
      {
        server: "notes",
        uri: "notes://plan",
        name: "plan.md",
        description: "The plan",
        mime_type: "text/markdown",
      },
    ]),
    attachResource: vi.fn(async () => ({
      id: "u1",
      kind: "document" as const,
      name: "notes: plan",
      chars: 20,
      truncated: false,
    })),
    prompts: vi.fn(async () => [
      {
        server: "notes",
        name: "summarise",
        title: "Summarise a topic",
        description: "",
        arguments: [{ name: "topic", description: "What about", required: true }],
      },
    ]),
    promptText: vi.fn(async (_id, _name, args) => `Write a summary of ${args.topic}.`),
  };
}

describe("the servers panel", () => {
  it("attaches a resource as a document and puts a filled-in prompt in the box", async () => {
    const c = control();
    const onAttach = vi.fn(() => true);
    const onInsert = vi.fn();
    const user = userEvent.setup();
    render(<ServersPanel control={c} onAttach={onAttach} onInsert={onInsert} onClose={() => {}} />);
    expect(await screen.findByText("plan.md")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Attach" }));
    await waitFor(() => expect(c.attachResource).toHaveBeenCalledWith("s1", "notes://plan"));
    expect(onAttach).toHaveBeenCalledWith(expect.objectContaining({ id: "u1", kind: "document" }));
    await user.click(screen.getByRole("button", { name: "Use" }));
    const put = screen.getByRole("button", { name: /put it in the box/i });
    expect(put).toBeDisabled(); // topic is required
    await user.type(screen.getByLabelText(/topic/), "foxes");
    await user.click(put);
    await waitFor(() => expect(onInsert).toHaveBeenCalledWith("Write a summary of foxes."));
  });

  it("says when there is no room for another attachment", async () => {
    const c = control();
    const user = userEvent.setup();
    render(
      <ServersPanel control={c} onAttach={() => false} onInsert={() => {}} onClose={() => {}} />,
    );
    await user.click(await screen.findByRole("button", { name: "Attach" }));
    expect(await screen.findByText(/no room for another attachment/i)).toBeInTheDocument();
  });
});
