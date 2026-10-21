import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AppSidebar } from "./AppSidebar";

let path = "/text-to-speech";
let query = "";
vi.mock("next/navigation", () => ({
  usePathname: () => path,
  useSearchParams: () => new URLSearchParams(query),
  useRouter: () => ({ push: vi.fn() }),
}));

function panel(isAdmin = false, notebooks = false, voice = false) {
  render(
    <TooltipProvider>
      <SidebarProvider>
        <AppSidebar
          isAdmin={isAdmin}
          footer={<span>Ada</span>}
          notebooks={notebooks}
          voice={voice}
        />
      </SidebarProvider>
    </TooltipProvider>,
  );
}

describe("the side panel", () => {
  it("is the desktop's menu: the groups in order, with the page's group open", () => {
    path = "/voice/speak";
    query = "";
    panel(false, false, true);
    for (const name of ["Notebook", "Images", "Video", "Voice", "Music"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Voice" })).toHaveAttribute("aria-expanded", "true");
    const here = screen.getByRole("link", { name: /Text to speech/ });
    expect(here).toHaveAttribute("href", "/voice/speak");
    expect(here).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Speech to text/ })).toHaveAttribute(
      "href",
      "/voice/transcribe",
    );
    // the other voice screens are linked only where a ready model can run them
    expect(screen.queryByRole("link", { name: /Lip sync/ })).toBeNull();
  });

  it("links each product's create page and its saved results", async () => {
    path = "/image";
    query = "";
    panel();
    expect(screen.getByRole("link", { name: /Create/ })).toHaveAttribute("href", "/image");
    expect(screen.getByRole("link", { name: /Your images/ })).toHaveAttribute(
      "href",
      "/image/library",
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Video/ }));
    expect(screen.getByRole("link", { name: /Your videos/ })).toHaveAttribute(
      "href",
      "/video/library",
    );
  });

  it("shows what the web does not serve yet as disabled, with a Soon tag", async () => {
    path = "/image";
    query = "";
    panel();
    expect(screen.getByRole("link", { name: /Edit/ })).toHaveAttribute("href", "/image/edit");
    const soon = screen.getByRole("button", { name: /Inpaint/ });
    expect(soon).toBeDisabled();
    expect(within(soon).getByText("Soon")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Notebook/ })).toBeInTheDocument();
    expect(screen.queryByText("Models")).not.toBeInTheDocument(); // the admin picks models here
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
    expect(screen.getByRole("link", { name: /new chat/i })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: /new chat/i })).not.toHaveAttribute("aria-current");
    expect(await screen.findByRole("button", { name: "Fox poem" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: "Budget" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: /Explore/ })).toHaveAttribute("href", "/explore");
    vi.unstubAllGlobals();
  });

  it("marks the page being shown, a saved result as its library, and the filter of My creations", () => {
    path = "/video/library";
    query = "";
    const first = render(
      <TooltipProvider>
        <SidebarProvider>
          <AppSidebar isAdmin={false} footer={null} />
        </SidebarProvider>
      </TooltipProvider>,
    );
    expect(screen.getByRole("link", { name: /Your videos/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    first.unmount();

    path = "/image/creations/abc";
    const second = render(
      <TooltipProvider>
        <SidebarProvider>
          <AppSidebar isAdmin={false} footer={null} />
        </SidebarProvider>
      </TooltipProvider>,
    );
    expect(screen.getByRole("link", { name: /Your images/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: /Create/ })).not.toHaveAttribute("aria-current");
    second.unmount();
  });

  it("shows My creations as the library, and the admin link only to admins", () => {
    path = "/creations";
    query = "";
    panel(false);
    expect(screen.getByRole("link", { name: /Library/ })).toHaveAttribute("href", "/creations");
    expect(screen.getByRole("link", { name: /Library/ })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: /Admin/ })).not.toBeInTheDocument();
  });

  it("shows the admin link to admins, the brand as a link home and the footer it is given", () => {
    path = "/image";
    query = "";
    panel(true);
    expect(screen.getByRole("link", { name: /Admin/ })).toHaveAttribute("href", "/admin");
    expect(screen.getByRole("link", { name: "Wasify AI, home" })).toHaveAttribute("href", "/");
    expect(screen.getByText("Ada")).toBeInTheDocument();
  });

  it("opens the shared speech screens when the voice product is on", async () => {
    path = "/voice/speak";
    query = "";
    panel(false, false, true);
    expect(screen.getByRole("link", { name: /Text to speech/ })).toHaveAttribute(
      "href",
      "/voice/speak",
    );
    expect(screen.getByRole("link", { name: /Speech to text/ })).toHaveAttribute(
      "href",
      "/voice/transcribe",
    );
  });
});
