import { beforeEach, describe, expect, it, vi } from "vitest";

const save = vi.fn();
const fetchMock = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ save: (o: unknown) => save(o) }));
vi.mock("@tauri-apps/api/path", () => ({
  downloadDir: async () => "/Users/me/Downloads",
  join: async (...parts: string[]) => parts.join("/"),
}));
vi.mock("./api", () => ({ transport: { fetch: (p: string, i: unknown) => fetchMock(p, i) } }));

import { saveAs } from "./save-as";

beforeEach(() => {
  save.mockReset();
  fetchMock.mockReset();
});

describe("the Save As box", () => {
  it("opens in the system's Downloads folder with the suggested name and returns the chosen path", async () => {
    save.mockResolvedValue("/Users/me/Desktop/fox.mp4");
    expect(await saveAs.choose("fox.mp4")).toBe("/Users/me/Desktop/fox.mp4");
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({ defaultPath: "/Users/me/Downloads/fox.mp4" }),
    );
  });

  it("returns null when the person cancels", async () => {
    save.mockResolvedValue(null);
    expect(await saveAs.choose("fox.mp4")).toBeNull();
  });

  it("sends the file and its path to the engine and says where it was saved", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ name: "a.wav", path: "/tmp/a.wav" }), { status: 200 }),
    );
    const saved = await saveAs.write("/tmp/a.wav", new Blob(["RIFF"]));
    expect(saved).toEqual({ name: "a.wav", path: "/tmp/a.wav" });
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/desktop/save");
    expect((init.body as FormData).get("path")).toBe("/tmp/a.wav");
    expect((init.body as FormData).get("file")).toBeInstanceOf(Blob);
  });

  it("says in words what the engine refused", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "That folder does not exist. Choose another." }), {
        status: 422,
      }),
    );
    await expect(saveAs.write("/nope/a.wav", new Blob(["x"]))).rejects.toThrow("does not exist");
  });
});
