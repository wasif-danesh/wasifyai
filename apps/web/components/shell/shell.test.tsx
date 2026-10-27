import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AppSidebar } from "./AppSidebar";

let path = "/text-to-speech";
let query = "";
vi.mock("next/navigation", () => ({
  usePathname: () => path,
  useSearchParams: () => new URLSearchParams(query),
  useRouter: () => ({ push: vi.fn() }),
}));

function panel(isAdmin = false) {
  render(
    <TooltipProvider>
      <SidebarProvider>
        <AppSidebar isAdmin={isAdmin} footer={<span>Ada</span>} />
      </SidebarProvider>
    </TooltipProvider>,
  );
}

describe("the side panel", () => {
  it("is the desktop's menu: eleven entries, one click each, the page's entry marked", () => {
    path = "/voice/speak";
    query = "";
    panel(false);
    for (const name of ["Chat", "Notebooks", "Images", "Video", "Speech", "Library"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
    // music and the studio tools are linked only where a ready model can run them: Soon until then
    expect(screen.getByRole("button", { name: /^Music/ })).toBeDisabled();
    const here = screen.getByRole("link", { name: "Speech" });
    expect(here).toHaveAttribute("href", "/voice/speak");
    expect(here).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button", { expanded: true })).toBeNull(); // no group to open
    expect(screen.getByRole("button", { name: /^Studio/ })).toBeDisabled();
  });

  it("opens each product on its create page and stays on the page that is open", () => {
    path = "/image/library";
    query = "";
    panel();
    expect(screen.getByRole("link", { name: "Images" })).toHaveAttribute("href", "/image/library");
    expect(screen.getByRole("link", { name: "Video" })).toHaveAttribute("href", "/video");
    expect(screen.getByRole("link", { name: "3D model" })).toHaveAttribute("href", "/image/3d");
    expect(screen.getByRole("link", { name: "Train models" })).toHaveAttribute("href", "/train");
    expect(screen.queryByText("Model hub")).not.toBeInTheDocument(); // the admin picks models here
  });

  it("starts a new chat from the home page, marks a chat that is open, and lists Explore", async () => {
    path = "/chat/0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80";
    query = "";
    const fetchMock = vi.fn(async () =>
      Response.json({
        conversations: [
          {
            id: "0f3c1a52-7a49-4d1e-9a31-8f1d5b6c7d80",
            title: "Fox poem",
            created_at: "",
            updated_at: "",
          },
          { id: "b", title: "Budget", created_at: "", updated_at: "" },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    panel();
    expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Chat" })).not.toHaveAttribute("aria-current");
    expect(await screen.findByRole("button", { name: "Fox poem" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: "Budget" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: /Explore/ })).toHaveAttribute("href", "/explore");
    vi.unstubAllGlobals();
  });

  it("marks a product's saved result as that product", () => {
    path = "/image/creations/abc";
    query = "";
    panel();
    expect(screen.getByRole("link", { name: "Images" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Video" })).not.toHaveAttribute("aria-current");
  });

  it("shows My creations as the library, and the admin link only to admins", () => {
    path = "/creations";
    query = "";
    panel(false);
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute("href", "/creations");
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: /Admin/ })).not.toBeInTheDocument();
  });

  it("shows the admin link to admins, the brand as a link home and the footer it is given", () => {
    path = "/image";
    query = "";
    panel(true);
    expect(screen.getByRole("link", { name: /Admin/ })).toHaveAttribute("href", "/admin");
    expect(screen.getByRole("link", { name: "Model hub" })).toHaveAttribute(
      "href",
      "/admin/workers",
    );
    expect(screen.getByRole("link", { name: "Wasify AI, home" })).toHaveAttribute("href", "/");
    expect(screen.getByText("Ada")).toBeInTheDocument();
  });
});
