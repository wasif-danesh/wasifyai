// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NavLink } from "./NavLink";

const pathname = vi.hoisted(() => ({ value: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.value }));

describe("NavLink", () => {
  it("marks the current page, including its sub-pages", () => {
    pathname.value = "/songs/abc";
    render(
      <>
        <NavLink href="/">Create</NavLink>
        <NavLink href="/songs">My songs</NavLink>
      </>,
    );
    expect(screen.getByRole("link", { name: "My songs" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Create" })).not.toHaveAttribute("aria-current");
  });

  it("only marks the home link on exactly the home page", () => {
    pathname.value = "/";
    render(<NavLink href="/">Create</NavLink>);
    expect(screen.getByRole("link", { name: "Create" })).toHaveAttribute("aria-current", "page");
  });
});
