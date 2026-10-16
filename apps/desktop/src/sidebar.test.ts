import { describe, expect, it } from "vitest";
import { GROUPS, groupOf } from "./Sidebar";

describe("the side menu", () => {
  it("has the groups in order, each with its items", () => {
    expect(GROUPS.map((g) => g.label)).toEqual(["Notebook", "Images", "Video", "Voice", "Music"]);
    const items = (id: string) => GROUPS.find((g) => g.id === id)?.items.map((i) => i.label);
    expect(items("notebook")).toEqual(["Create", "View Notebooks"]);
    expect(items("video")).toEqual(["Create", "Animate an image", "Extend video", "Your videos"]);
    expect(items("voice")).toEqual(["Text to speech", "Speech to text", "Lip sync", "Voices"]);
    expect(items("music")).toEqual(["Create", "Your music", "Lyrics"]);
    expect(items("images")).toContain("Your images");
  });

  it("marks what is not built yet, and nothing in Notebook or Images' working tools", () => {
    for (const id of ["video", "voice", "music"]) {
      expect(GROUPS.find((g) => g.id === id)?.items.every((i) => i.soon)).toBe(true);
    }
    const notebook = GROUPS.find((g) => g.id === "notebook");
    expect(notebook?.items.some((i) => i.soon)).toBe(false);
    const images = GROUPS.find((g) => g.id === "images")?.items ?? [];
    expect(images.filter((i) => !i.soon).map((i) => i.label)).toEqual([
      "Create",
      "Edit",
      "Your images",
    ]);
  });

  it("keeps the group of the current page open", () => {
    expect(groupOf("notebook")).toBe("notebook");
    expect(groupOf("notebooks")).toBe("notebook");
    expect(groupOf("create")).toBe("images");
    expect(groupOf("library")).toBe("images");
    expect(groupOf("home")).toBeNull();
    expect(groupOf("models")).toBeNull();
  });

  it("tells a draft from a saved notebook", () => {
    const [create, view] = GROUPS[0]?.items ?? [];
    expect(create?.current?.("notebook", "new")).toBe(true);
    expect(create?.current?.("notebook", "abc")).toBe(false);
    expect(view?.current?.("notebook", "abc")).toBe(true);
    expect(view?.current?.("notebooks", null)).toBe(true);
    expect(view?.current?.("home", null)).toBe(false);
  });
});
