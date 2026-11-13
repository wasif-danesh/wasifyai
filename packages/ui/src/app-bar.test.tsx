// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AppBar } from "./app-bar";
import { PageHeader, WindowBarProvider } from "./window-bar";

function Window({ header }: { header: "none" | "tools" | "title" }) {
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
      <AppBar title="Images" showTitle={claims === 0} slot={setSlot} theme={false} />
      {header === "tools" ? (
        <PageHeader>
          <button type="button">FLUX.2 klein 4B</button>
        </PageHeader>
      ) : null}
      {header === "title" ? (
        <PageHeader title>
          <h1>Launch plan</h1>
        </PageHeader>
      ) : null}
    </WindowBarProvider>
  );
}

describe("the one top bar", () => {
  it("shows the title, which is not a heading: the screen's own h1 is the page's one heading", () => {
    render(<AppBar title="Images" theme={false} />);
    expect(screen.getByText("Images")).toHaveAttribute("data-slot", "app-bar-title");
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("keeps its title while a screen only adds its tools, and yields it to a screen's own title", () => {
    const { rerender } = render(<Window header="tools" />);
    expect(screen.getByText("Images")).toHaveAttribute("data-slot", "app-bar-title");
    expect(screen.getByRole("button", { name: "FLUX.2 klein 4B" })).toBeInTheDocument();
    rerender(<Window header="title" />);
    expect(screen.queryByText("Images")).toBeNull();
    expect(screen.getByRole("heading", { name: "Launch plan" })).toBeInTheDocument();
  });

  it("opens search from its button and from ⌘K", async () => {
    const search = vi.fn();
    render(<AppBar title="Chat" theme={false} onSearch={search} />);
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(search).toHaveBeenCalledTimes(1);
    await userEvent.keyboard("{Meta>}k{/Meta}");
    expect(search).toHaveBeenCalledTimes(2);
  });

  it("has a theme switch", async () => {
    render(<AppBar title="Chat" />);
    const button = await screen.findByRole("button", { name: /Switch to the (dark|light) theme/ });
    await userEvent.click(button);
    expect(["light", "dark"]).toContain(document.documentElement.dataset.theme);
  });
});
