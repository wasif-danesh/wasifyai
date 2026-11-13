// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  type SaveAs,
  SaveAsProvider,
  extensionOf,
  fileNameFor,
  savedText,
  useSaveCopy,
} from "./save";

function withDialog(dialog: SaveAs | null) {
  return ({ children }: { children: ReactNode }) => (
    <SaveAsProvider value={dialog}>{children}</SaveAsProvider>
  );
}

describe("names", () => {
  it("makes a short readable file name, whatever the words", () => {
    expect(fileNameFor("A red fox, in the snow!", "mp4")).toBe("a-red-fox-in-the-snow.mp4");
    expect(fileNameFor("Café – Résumé", "pdf")).toBe("cafe-resume.pdf");
    expect(fileNameFor("   ", "png", "picture")).toBe("picture.png");
    expect(fileNameFor("x".repeat(100), "wav").length).toBe(48 + 4);
    expect(fileNameFor("one", ".glb")).toBe("one.glb");
  });

  it("finds an extension in a name or an address", () => {
    expect(extensionOf("http://127.0.0.1:1/files/a/video.webm?e=1&s=2", "mp4")).toBe("webm");
    expect(extensionOf("report.DOCX", "bin")).toBe("docx");
    expect(extensionOf("no-extension", "png")).toBe("png");
    expect(extensionOf("http://host/path/", "png")).toBe("png");
  });

  it("says where a copy went", () => {
    expect(savedText({ name: "a.mp4", path: "/Users/me/Movies/a.mp4" })).toBe(
      "Saved as a.mp4 in Movies.",
    );
    expect(savedText({ name: "a.mp4", path: "C:\\Users\\me\\Videos\\a.mp4" })).toBe(
      "Saved as a.mp4 in Videos.",
    );
    expect(savedText({ name: "a.mp4" })).toBe("Saved as a.mp4.");
  });
});

describe("saving a copy", () => {
  it("in the app window asks where, and the engine copies its own file to the chosen path", async () => {
    const choose = vi.fn(async () => "/Users/me/Desktop/fox.mp4");
    const copy = vi.fn(async (path?: string) => ({ name: "fox.mp4", path }));
    const write = vi.fn();
    const { result } = renderHook(() => useSaveCopy(), {
      wrapper: withDialog({ choose, write }),
    });
    const saved = await result.current({ name: "fox.mp4", copy, blob: vi.fn() });
    expect(choose).toHaveBeenCalledWith("fox.mp4");
    expect(copy).toHaveBeenCalledWith("/Users/me/Desktop/fox.mp4");
    expect(saved).toEqual({ name: "fox.mp4", path: "/Users/me/Desktop/fox.mp4" });
    expect(write).not.toHaveBeenCalled();
  });

  it("in the app window writes the bytes it holds at the chosen path", async () => {
    const data = new Blob(["x"]);
    const write = vi.fn(async (path: string) => ({ name: "speech.wav", path }));
    const { result } = renderHook(() => useSaveCopy(), {
      wrapper: withDialog({ choose: async () => "/tmp/speech.wav", write }),
    });
    const saved = await result.current({ name: "speech.wav", blob: async () => data });
    expect(write).toHaveBeenCalledWith("/tmp/speech.wav", data);
    expect(saved?.path).toBe("/tmp/speech.wav");
  });

  it("does nothing when the person cancels the box: no file is read, none is written", async () => {
    const copy = vi.fn();
    const blob = vi.fn();
    const write = vi.fn();
    const { result } = renderHook(() => useSaveCopy(), {
      wrapper: withDialog({ choose: async () => null, write }),
    });
    expect(await result.current({ name: "a.txt", copy, blob })).toBeNull();
    expect(copy).not.toHaveBeenCalled();
    expect(blob).not.toHaveBeenCalled();
    expect(write).not.toHaveBeenCalled();
  });

  it("without a box uses the engine's folder when the engine keeps the file", async () => {
    const copy = vi.fn(async () => ({ name: "a.png", path: "/x/Downloads/a.png" }));
    const { result } = renderHook(() => useSaveCopy(), { wrapper: withDialog(null) });
    await result.current({ name: "a.png", copy });
    expect(copy).toHaveBeenCalledWith();
  });

  it("on the web the browser saves the file", async () => {
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const { result } = renderHook(() => useSaveCopy(), { wrapper: withDialog(null) });
    const saved = await result.current({ name: "plan.docx", blob: async () => new Blob(["x"]) });
    expect(click).toHaveBeenCalled();
    expect(saved).toEqual({ name: "plan.docx" });
    click.mockRestore();
  });
});
