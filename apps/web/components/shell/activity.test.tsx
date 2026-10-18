// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Activity } from "./Activity";

vi.mock("@/hooks/use-video-activity", () => ({
  useVideoActivity: () => ({
    working: [],
    notice: { id: "x", status: "failed", prompt: "Hello", error: "It failed." },
    dismiss: vi.fn(),
  }),
}));

describe("Activity", () => {
  it("puts the notice on the page, not inside the top bar that holds it", () => {
    // the bar's blur makes it the containing block of fixed children, which hid the notice
    render(
      <header data-testid="bar">
        <Activity enabled />
      </header>,
    );
    const notice = screen.getByText("Your video couldn't be made");
    expect(notice).toBeInTheDocument();
    expect(screen.getByTestId("bar")).not.toContainElement(notice);
    expect(document.body).toContainElement(notice);
  });
});
