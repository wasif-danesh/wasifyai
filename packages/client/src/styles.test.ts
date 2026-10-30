import { describe, expect, it } from "vitest";
import { StyleError, createStylesApi } from "./styles";
import { HttpError, type Transport } from "./transport";

type Call = { path: string; init?: RequestInit };

function fake(answer: (path: string, init?: RequestInit) => Response) {
  const calls: Call[] = [];
  const transport: Transport = {
    async fetch(path, init) {
      calls.push({ path, init });
      return answer(path, init);
    },
    onUnauthorized() {},
  };
  return { transport, calls };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("the styles client", () => {
  it("lists, imports the file itself, copies a found one, edits and deletes on /desktop/styles", async () => {
    const { transport, calls } = fake((_path, init) =>
      init?.method === "DELETE" ? new Response(null, { status: 204 }) : json({ id: "s1" }),
    );
    const api = createStylesApi(transport);
    await api.list();
    const file = new Blob([new Uint8Array([1, 2, 3])]);
    await api.importFile(file, "My style (v2).safetensors");
    await api.fromFound("f1");
    await api.update("s1", { trigger: "ink" });
    expect(await api.remove("s1")).toBeUndefined();
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path])).toEqual([
      ["GET", "/desktop/styles"],
      ["POST", "/desktop/styles/import?name=My%20style%20(v2).safetensors"],
      ["POST", "/desktop/styles/from-found"],
      ["PATCH", "/desktop/styles/s1"],
      ["DELETE", "/desktop/styles/s1"],
    ]);
    expect(calls[1]?.init?.body).toBe(file); // the file goes as it is, never a path
  });

  it("says a refusal in the engine's words", async () => {
    const { transport } = fake(() =>
      json(
        { detail: { code: "style_refused", message: "This is a model, not a style (a LoRA)." } },
        422,
      ),
    );
    const err = await createStylesApi(transport)
      .importFile(new Blob([]), "x.safetensors")
      .catch((e) => e);
    expect(err).toBeInstanceOf(HttpError);
    expect(err.message).toBe("This is a model, not a style (a LoRA).");
  });

  it("asks Hugging Face through the engine, and says when browsing is not allowed yet", async () => {
    const { transport, calls } = fake((path) =>
      path.endsWith("/hub/files")
        ? json({ detail: { code: "consent_needed", message: "Turn it on first." } }, 403)
        : json({ id: "d1" }),
    );
    const api = createStylesApi(transport);
    const err = await api.hubFiles("owner/name").catch((e) => e);
    expect(err).toBeInstanceOf(StyleError);
    expect([err.status, err.code]).toEqual([403, "consent_needed"]);
    await api.allowHub();
    await api.hubDownload("owner/name", "a.safetensors", 9);
    await api.hubJob("d1");
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path, c.init?.body ?? null])).toEqual([
      ["POST", "/desktop/styles/hub/files", JSON.stringify({ repo: "owner/name" })],
      ["PUT", "/desktop/hub/consent", JSON.stringify({ enabled: true })],
      [
        "POST",
        "/desktop/styles/hub/download",
        JSON.stringify({ repo: "owner/name", file: "a.safetensors", bytes: 9 }),
      ],
      ["GET", "/desktop/styles/hub/downloads/d1", null],
    ]);
  });

  it("keeps saved looks with styles by id and strength only", async () => {
    const { transport, calls } = fake((_p, init) =>
      init?.method === "DELETE" ? new Response(null, { status: 204 }) : json({ looks: [] }),
    );
    const api = createStylesApi(transport);
    expect(await api.looks()).toEqual([]);
    await api.saveLook({
      name: "Ink",
      size: "wide",
      width: null,
      height: null,
      steps: 6,
      styles: [{ id: "a1", strength: 0.7, sha256: "x", title: "Ink" }],
    }); // fmt: skip
    await api.deleteLook("Ink wide");
    expect(calls.map((c) => [c.init?.method ?? "GET", c.path])).toEqual([
      ["GET", "/desktop/styles/looks"],
      ["PUT", "/desktop/styles/looks"],
      ["DELETE", "/desktop/styles/looks/Ink%20wide"],
    ]); // fmt: skip
    expect(JSON.parse(String(calls[1]?.init?.body)).styles).toEqual([{ id: "a1", strength: 0.7 }]);
  });
});
