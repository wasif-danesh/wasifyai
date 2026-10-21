// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { TitleBar } from "./title-bar";
import { PageHeader, WindowBarProvider } from "./window-bar";

function Window({ withHeader }: { withHeader: boolean }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const [claims, setClaims] = useState(0);
  const bar = slot
    ? {
        target: slot,
        claim: () => {
          setClaims((n) => n + 1);
          return () => setClaims((n) => n - 1);
        },
      }
    : null;
  return (
    <WindowBarProvider bar={bar}>
      <TitleBar
        menuOpen
        onToggleMenu={() => {}}
        canGoBack={false}
        canGoForward
        title="Video: Create"
        showTitle={claims === 0}
        slot={setSlot}
      />
      {withHeader ? (
        <PageHeader className="inline-header">
          <h1>Launch plan</h1>
          <button type="button">Rename</button>
        </PageHeader>
      ) : null}
    </WindowBarProvider>
  );
}

describe("the top bar of the window", () => {
  it("has back, forward and the menu button in a row, back disabled when there is nowhere to go", async () => {
    const toggle = vi.fn();
    const user = userEvent.setup();
    render(
      <TitleBar
        menuOpen={false}
        onToggleMenu={toggle}
        canGoBack={false}
        canGoForward
        title="Models"
        showTitle
        slot={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Forward" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Show the side menu" }));
    expect(toggle).toHaveBeenCalled();
    expect(screen.getByText("Models")).toBeInTheDocument();
  });

  it("can be dragged by its bare parts: the bar and both halves are drag regions, its text is not in the way", () => {
    const { container } = render(
      <TitleBar
        menuOpen
        onToggleMenu={() => {}}
        canGoBack
        canGoForward
        title="Models"
        showTitle
        slot={() => {}}
      />,
    );
    expect(container.querySelectorAll("[data-tauri-drag-region]")).toHaveLength(3);
    expect(screen.getByText("Models").className).toContain("pointer-events-none");
  });

  it("says the screen's name until a screen puts its own header in the bar, and the header is then in the bar", async () => {
    const { container, rerender } = render(<Window withHeader={false} />);
    expect(screen.getByText("Video: Create")).toBeInTheDocument();
    rerender(<Window withHeader />);
    const heading = await screen.findByRole("heading", { name: "Launch plan" });
    expect(container.querySelector("[data-tauri-drag-region]")?.contains(heading)).toBe(true);
    expect(container.querySelector(".inline-header")).toBeNull(); // not a header of the page
    expect(screen.queryByText("Video: Create")).toBeNull(); // the screen's own title replaces it
    rerender(<Window withHeader={false} />);
    expect(await screen.findByText("Video: Create")).toBeInTheDocument();
  });

  it("keeps tools marked for the page out of the bar, and shows them in a header of the page", async () => {
    function Bare({ inBar }: { inBar: boolean }) {
      const [slot, setSlot] = useState<HTMLElement | null>(null);
      const bar = inBar && slot ? { target: slot, claim: () => () => {} } : null;
      return (
        <WindowBarProvider bar={bar}>
          <TitleBar
            menuOpen
            onToggleMenu={() => {}}
            canGoBack={false}
            canGoForward={false}
            title="x"
            showTitle={false}
            slot={setSlot}
          />
          <PageHeader pageOnly={<button type="button">Delete this chat</button>}>
            <h1>What is the date?</h1>
          </PageHeader>
        </WindowBarProvider>
      );
    }
    const { rerender } = render(<Bare inBar />);
    expect(await screen.findByRole("heading", { name: "What is the date?" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete this chat" })).toBeNull(); // not in the bar
    rerender(<Bare inBar={false} />);
    expect(await screen.findByRole("button", { name: "Delete this chat" })).toBeInTheDocument();
  });

  it("is a header of the page where there is no window bar (the web)", () => {
    const { container } = render(
      <PageHeader className="inline-header">
        <h1>Launch plan</h1>
      </PageHeader>,
    );
    expect(container.querySelector("header.inline-header h1")?.textContent).toBe("Launch plan");
  });
});
