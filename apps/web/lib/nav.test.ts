import { describe, expect, it } from "vitest";
import { crumbs, isCurrent, productOf } from "./nav";

describe("navigation helpers", () => {
  it("finds the product a path belongs to", () => {
    expect(productOf("/image")?.id).toBe("image");
    expect(productOf("/video/creations/abc")?.id).toBe("video");
    expect(productOf("/imagery")).toBeUndefined();
    expect(productOf("/creations")).toBeUndefined();
  });

  it("builds the breadcrumb from the product down", () => {
    expect(crumbs("/image")).toEqual([{ label: "Image" }]);
    expect(crumbs("/video/creations/1")).toEqual([
      { label: "Video", href: "/video" },
      { label: "Saved result" },
    ]);
    expect(crumbs("/video/library")).toEqual([
      { label: "Video", href: "/video" },
      { label: "Library" },
    ]);
    expect(crumbs("/image/edit")).toEqual([{ label: "Image", href: "/image" }, { label: "Edit" }]);
    expect(crumbs("/notebooks")).toEqual([{ label: "Notebooks" }]);
    expect(crumbs("/notebooks/new")).toEqual([
      { label: "Notebooks", href: "/notebooks" },
      { label: "New notebook" },
    ]);
    expect(crumbs("/notebooks/abc")).toEqual([
      { label: "Notebooks", href: "/notebooks" },
      { label: "Notebook" },
    ]);
    expect(crumbs("/creations")).toEqual([{ label: "My creations" }]);
    expect(crumbs("/somewhere")).toEqual([]);
  });

  it("matches a link to the whole of its area", () => {
    expect(isCurrent("/music/songs/1", "/music")).toBe(true);
    expect(isCurrent("/musical", "/music")).toBe(false);
  });
});

describe("Motion graphics", () => {
  it("has its own breadcrumb, not one under Video", () => {
    expect(crumbs("/video/builder")).toEqual([{ label: "Motion graphics" }]);
  });

  it("shows the 3D model on its own too", () => {
    expect(crumbs("/image/3d")).toEqual([{ label: "3D model" }]);
  });
});
