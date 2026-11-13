import { NEW_NOTEBOOK } from "@/lib/notebook-ids";
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NotebookListScreen, NotebookScreen } from "./NotebookScreens";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
  usePathname: () => "/notebooks",
}));

const fetchMock = vi.fn();
beforeEach(() => {
  sessionStorage.clear();
  push.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const ID = "0f3c1a527a494d1e9a318f1d5b6c7d80";
const summary = (over = {}) => ({
  id: ID,
  title: "Launch plan",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  opened_at: null,
  sources: 2,
  ready: 2,
  reading: 0,
  failed: 0,
  ...over,
});

describe("NotebookListScreen", () => {
  it("lists the notebooks through the BFF and opens or starts one", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/products/wasifyai-notebooks/notebooks")) {
        return Response.json([summary()]);
      }
      return Response.json({});
    });
    const user = userEvent.setup();
    render(<NotebookListScreen />);
    await user.click(await screen.findByText("Launch plan"));
    expect(push).toHaveBeenCalledWith(`/notebooks/${ID}`);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/products/wasifyai-notebooks/notebooks");
    await user.click(screen.getByRole("button", { name: /new notebook|create|add/i }));
    expect(push).toHaveBeenLastCalledWith(`/notebooks/${NEW_NOTEBOOK}`);
  });

  it("says why the notebooks cannot be listed", async () => {
    fetchMock.mockResolvedValue(
      Response.json(
        { detail: "Notebooks are not available in this deployment yet." },
        { status: 503 },
      ),
    );
    render(<NotebookListScreen />);
    expect(await screen.findByText(/not available in this deployment/i)).toBeInTheDocument();
  });
});

describe("NotebookScreen", () => {
  it("opens a saved notebook and reads it", async () => {
    fetchMock.mockImplementation(async (path: string) => {
      if (path.endsWith(`/notebooks/${ID}`)) return Response.json(summary());
      if (path.includes("/documents")) return Response.json([]);
      if (path.includes("/folders")) return Response.json([]);
      return Response.json([]);
    });
    render(<NotebookScreen notebook={ID} />);
    expect(await screen.findByDisplayValue("Launch plan")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith(`/notebooks/${ID}`))).toBe(true);
  });

  it("says plainly when a notebook is not there, and goes back to the list", async () => {
    fetchMock.mockResolvedValue(Response.json({ detail: "notebook not found" }, { status: 404 }));
    render(<NotebookScreen notebook={ID} />);
    expect(await screen.findByText("That notebook is not here")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to notebooks/i })).toHaveAttribute(
      "href",
      "/notebooks",
    );
  });

  it("starts as a draft that is not saved until something is added", async () => {
    fetchMock.mockImplementation(async () => Response.json([]));
    render(<NotebookScreen notebook={NEW_NOTEBOOK} />);
    expect(await screen.findByDisplayValue("Untitled notebook")).toBeInTheDocument();
    const created = fetchMock.mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method === "POST",
    );
    expect(created).toHaveLength(0);
  });
});
