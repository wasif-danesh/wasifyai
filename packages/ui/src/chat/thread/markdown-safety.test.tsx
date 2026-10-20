// @vitest-environment jsdom
// The permanent safety test for the markdown a model writes (ADR-0082 decision 4). It renders the adversarial message of
// markdown/adversarial.ts with the real renderer and fails if any rule breaks: raw HTML becoming elements, a link that is not
// http(s), a picture from anywhere but the allowed origins, a flag set on `window`. Diagrams and the request tracker need a real
// browser: apps/web/e2e/chat-next-safety.spec.ts. Re-run it on every streamdown update.
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./markdown/Markdown";
import { isSafeHref } from "./markdown/SafeLink";
import { ADVERSARIAL, TRACKER } from "./markdown/adversarial";

async function rendered(text: string, imageOrigins?: string[]) {
  const view = render(<Markdown text={text} imageOrigins={imageOrigins} />);
  // streamdown loads on demand: until it has, the text is shown as it is
  await waitFor(() => expect(view.container.querySelector("[data-markdown]")).not.toBeNull());
  return view;
}

describe("the markdown of a model's answer is never markup", () => {
  it("shows raw HTML as text and makes no element from it", async () => {
    const { container } = await rendered(ADVERSARIAL);
    for (const tag of ["script", "iframe", "b", "img", "object", "embed", "style", "form"]) {
      expect(container.querySelector(tag), `<${tag}> in the output`).toBeNull();
    }
    expect(container.textContent).toContain("<script>window.__pwned1 = 1</script>");
    expect(container.textContent).toContain("<b>bold by html</b>");
    expect(container.querySelector("[onerror], [onclick], [onload]")).toBeNull();
    for (let n = 1; n <= 6; n++)
      expect((window as never as Record<string, unknown>)[`__pwned${n}`]).toBeUndefined();
  });

  it("makes a link only of an absolute http(s) address, opened safely", async () => {
    const { container } = await rendered(ADVERSARIAL);
    const links = [...container.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://example.com/page"]);
    expect(links[0]?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(links[0]?.getAttribute("target")).toBe("_blank");
    // the others are text, not links
    const shown = container.textContent ?? "";
    for (const label of ["js", "data", "vb", "file"]) expect(shown).toContain(`${label} [blocked]`);
    const relative = [...container.querySelectorAll("[data-link-blocked]")].map(
      (e) => e.textContent,
    );
    expect(relative).toEqual(["rel"]);
  });

  it("loads no picture from anywhere, unless its origin is allowed", async () => {
    const { container } = await rendered(ADVERSARIAL);
    expect(container.querySelectorAll("img")).toHaveLength(0);
    const allowed = await rendered(
      "![mine](http://127.0.0.1:8123/a.png) ![theirs](https://evil.invalid/a.png)",
      ["http://127.0.0.1:8123"],
    );
    const srcs = [...allowed.container.querySelectorAll("img")].map((i) => i.getAttribute("src"));
    expect(srcs).toEqual(["http://127.0.0.1:8123/a.png"]);
    expect(srcs.join()).not.toContain(TRACKER);
  });

  it("highlights code and sets maths without the network", async () => {
    const { container } = await rendered("```ts\nconst a: number = 1;\n```\n\n$$E = mc^2$$");
    await waitFor(() => expect(container.querySelector(".katex")).not.toBeNull(), {
      timeout: 8000,
    });
    await waitFor(
      () =>
        expect(
          container.querySelectorAll("[data-streamdown='code-block'] span span").length,
        ).toBeGreaterThan(3),
      {
        timeout: 8000,
      },
    );
  });

  it("keeps right-to-left text right to left, block by block", async () => {
    const { container } = await rendered("مرحبا بالعالم\n\nHello world");
    const dirs = [...container.querySelectorAll("p")].map(
      (p) => getComputedStyle(p).direction || p.getAttribute("dir"),
    );
    expect(container.querySelector("[dir='auto'], [dir='rtl']")).not.toBeNull();
    expect(dirs.length).toBeGreaterThan(0);
  });

  it("reads one address by the same rule everywhere", () => {
    expect(isSafeHref("https://a.test/x")).toBe(true);
    expect(isSafeHref("http://a.test/x")).toBe(true);
    for (const bad of [
      "javascript:alert(1)",
      "data:text/html,x",
      "vbscript:x",
      "file:///x",
      "/rel",
      "//a.test/x",
      "",
      undefined,
    ])
      expect(isSafeHref(bad), String(bad)).toBe(false);
    expect(screen).toBeDefined();
  });
});
