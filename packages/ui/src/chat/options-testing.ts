// The chat box's "+" menu in tests (ADR-0093, stage U9): which options it offers, and choosing one.
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const PLUS = /^More options/;

/** The options in the "+" menu, as their words ("Thinking", "Search: on"); none when there is no menu. */
export async function moreOptions(): Promise<string[]> {
  const plus = screen.queryByRole("button", { name: PLUS });
  if (!plus) return [];
  await userEvent.click(plus);
  const items = (await screen.findAllByRole("menuitem")).map((i) => i.textContent ?? "");
  await userEvent.keyboard("{Escape}");
  return items;
}

/** Choose an option of the "+" menu. */
export async function chooseOption(name: RegExp): Promise<void> {
  await userEvent.click(await screen.findByRole("button", { name: PLUS }));
  await userEvent.click(await screen.findByRole("menuitem", { name }));
}
