// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MeetingPerson, MeetingsApi } from "@wasifyai/client";
import { describe, expect, it, vi } from "vitest";
import { People } from "./People";

const asha: MeetingPerson = {
  id: "p1",
  name: "Asha",
  created_at: "2026-11-16T10:00:00Z",
  meetings: 2,
  voices: 1,
  last_named: null,
};

const api = (people: MeetingPerson[]) =>
  ({
    people: vi.fn(async () => people),
    renamePerson: vi.fn(async (id: string, name: string) => ({ ...asha, id, name })),
    forgetPerson: vi.fn(async () => undefined),
  }) as unknown as MeetingsApi;

describe("People", () => {
  it("says how to begin when no one is named", async () => {
    const open = vi.fn();
    render(<People api={api([])} onOpenMeetings={open} />);
    expect(await screen.findByText("No one yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "View meetings" }));
    expect(open).toHaveBeenCalled();
  });

  it("lists people with their meetings and voiceprints; renames and forgets after asking", async () => {
    const a = api([asha]);
    render(<People api={a} />);
    const row = await screen.findByRole("listitem", { name: "Asha" });
    expect(within(row).getByText("2 meetings, 1 voiceprint")).toBeInTheDocument();

    await userEvent.click(within(row).getByRole("button", { name: /Rename/ }));
    const name = await screen.findByLabelText("Their name");
    await userEvent.clear(name);
    await userEvent.type(name, "Asha Rahman{Enter}");
    await waitFor(() => expect(a.renamePerson).toHaveBeenCalledWith("p1", "Asha Rahman"));

    await userEvent.click(screen.getByRole("button", { name: "Forget Asha" }));
    const dialog = await screen.findByRole("dialog", { hidden: true });
    expect(a.forgetPerson).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Forget", hidden: true }));
    await waitFor(() => expect(a.forgetPerson).toHaveBeenCalledWith("p1"));
  });
});
