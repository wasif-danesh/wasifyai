import { MENU_GROUPS } from "@wasifyai/ui";
import { describe, expect, it, vi } from "vitest";
import { ROUTES, resolveItem } from "./menu";
import { type Route, routePath } from "./router";

const ids = MENU_GROUPS.flatMap((g) => g.items.map((i) => i.id));
const at = (route: Route, notebook: string | null = null, conversationId: string | null = null) =>
  resolveItem(route, () => {}, { conversationId, notebook });

describe("the window's side menu", () => {
  it("opens a screen for everything that is built and marks the rest as soon", () => {
    const soon = ids.filter((id) => at("home")(id) === undefined);
    expect(soon).toEqual([
      "images.transform",
      "images.inpaint",
      "images.extend",
      "images.upscale",
      "images.reference",
      "video.extend",
    ]);
    expect(at("home")("train")).toBeUndefined();
  });

  it("shows Video Builder only while its Labs switch is on", () => {
    const off = resolveItem("home", () => {}, { conversationId: null, notebook: null });
    const on = resolveItem("home", () => {}, {
      conversationId: null,
      notebook: null,
      videoBuilder: true,
    });
    expect(off("video.builder")).toEqual({ hidden: true });
    const shown = on("video.builder");
    expect(shown && !("hidden" in shown) ? shown.current : null).toBe(false);
    const open = resolveItem("videobuilder", () => {}, {
      conversationId: null,
      notebook: null,
      videoBuilder: true,
    })("video.builder");
    expect(open && !("hidden" in open) ? open.current : null).toBe(true);
    expect(routePath("videobuilder")).toBe("/video/builder");
  });

  it("points every item at a route that exists", () => {
    for (const [id, route] of Object.entries(ROUTES)) {
      expect(routePath(route), id).toBeTruthy();
      expect(ids.includes(id) || ["library", "models"].includes(id), id).toBe(true);
    }
  });

  it("marks the page being shown", () => {
    const current = (route: Route, id: string) => {
      const v = at(route)(id);
      return v && !("hidden" in v) ? v.current : false;
    };
    expect(current("video", "video.create")).toBe(true);
    expect(current("animate", "video.create")).toBe(false);
    expect(current("videos", "video.library")).toBe(true);
    expect(current("tracks", "music.library")).toBe(true);
    expect(current("speechedit", "voice.edit")).toBe(true);
    expect(current("models", "models")).toBe(true);
  });

  it("tells a new chat from an open one, and a draft notebook from a saved one", () => {
    const view = (route: Route, id: string, nb: string | null, conv: string | null) => {
      const v = at(route, nb, conv)(id);
      return v && !("hidden" in v) ? v.current : null;
    };
    expect(view("home", "chat", null, null)).toBe(true);
    expect(view("home", "chat", null, "abc")).toBe(false);
    expect(view("notebook", "notebook.create", "new", null)).toBe(true);
    expect(view("notebook", "notebook.create", "abc", null)).toBe(false);
    expect(view("notebook", "notebook.list", "abc", null)).toBe(true);
    expect(view("notebooks", "notebook.list", null, null)).toBe(true);
    expect(view("notebook", "notebook.list", "new", null)).toBe(false);
  });

  it("goes to the screen when an item is chosen", () => {
    const go = vi.fn();
    const v = resolveItem("home", go, { conversationId: null, notebook: null })("video.animate");
    if (!v || "hidden" in v) throw new Error("no view");
    v.onSelect?.();
    expect(go).toHaveBeenCalledWith("animate");
  });
});
