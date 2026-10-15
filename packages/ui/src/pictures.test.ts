import { describe, expect, it } from "vitest";
import { MAX_UPLOAD_BYTES, fileProblem, firstFile, hasFiles } from "./pictures";

const file = (bytes = 10, type = "image/png", name = "a.png") =>
  new File([new Uint8Array(bytes)], name, { type });

describe("fileProblem", () => {
  it("accepts png, jpeg and webp and rejects the rest", () => {
    expect(fileProblem(file())).toBeNull();
    expect(fileProblem(file(10, "image/jpeg"))).toBeNull();
    expect(fileProblem(file(10, "image/webp"))).toBeNull();
    expect(fileProblem(file(10, "image/gif"))).toMatch(/PNG, JPEG or WebP/);
    expect(fileProblem(file(MAX_UPLOAD_BYTES + 1))).toMatch(/10 MB/);
    expect(fileProblem(file(0))).toMatch(/empty/);
  });
});

describe("firstFile and hasFiles", () => {
  it("finds the first file, names a nameless paste, and ignores text", () => {
    const f = file();
    expect(firstFile({ items: [{ kind: "file", getAsFile: () => f }], files: [] } as never)).toBe(
      f,
    );
    const bare = new File([new Uint8Array(3)], "", { type: "image/jpeg" });
    expect(firstFile({ items: [{ kind: "file", getAsFile: () => bare }] } as never)?.name).toBe(
      "pasted-picture.jpg",
    );
    expect(
      firstFile({ items: [{ kind: "string", getAsFile: () => null }], files: [] } as never),
    ).toBeNull();
    expect(firstFile(null)).toBeNull();
    expect(firstFile({ items: [], files: [f] } as never)).toBe(f);
  });

  it("highlights only drags that carry files", () => {
    expect(hasFiles({ types: ["Files"] })).toBe(true);
    expect(hasFiles({ types: ["text/plain", "text/uri-list"] })).toBe(false);
    expect(hasFiles(null)).toBe(false);
  });
});
