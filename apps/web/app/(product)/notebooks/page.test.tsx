import { describe, expect, it } from "vitest";
import NotebookPage from "./[id]/page";

const open = (id: string) => NotebookPage({ params: Promise.resolve({ id }) });

describe("the notebook address", () => {
  // the draft's address was once a reference to a client file's export, so `/notebooks/new` answered 404
  it("opens a draft at /notebooks/new and a saved notebook by its id", async () => {
    await expect(open("new")).resolves.toBeTruthy();
    await expect(open("0123456789abcdef0123456789abcdef")).resolves.toBeTruthy();
  });

  it("answers not found for anything else", async () => {
    await expect(open("abc")).rejects.toThrow();
  });
});
