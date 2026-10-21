// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown, inline, parseBlocks } from "./markdown";

describe("markdown", () => {
  it("makes blocks of headings, lists, code and paragraphs", () => {
    const blocks = parseBlocks(
      "# Title\n\nSome *text*.\n\n- one\n- two\n\n1. a\n2. b\n\n```js\nlet x = 1;\n```",
    );
    expect(blocks.map((b) => b.kind)).toEqual(["heading", "p", "ul", "ol", "code"]);
    expect(blocks[4]).toEqual({ kind: "code", lang: "js", text: "let x = 1;" });
  });

  it("runs an unclosed code block to the end, as a half-streamed answer is", () => {
    const blocks = parseBlocks("Here:\n```py\nprint(1)");
    expect(blocks[1]).toEqual({ kind: "code", lang: "py", text: "print(1)" });
  });

  it("never makes markup of what a model writes, and only links http(s)", () => {
    const { container } = render(
      <Markdown
        text={"<script>alert(1)</script> [ok](https://example.com) [bad](javascript:alert(1))"}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    const links = [...container.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://example.com"]);
    expect(links[0]?.getAttribute("rel")).toContain("noopener");
    expect(container.textContent).toContain("[bad](javascript:alert(1))");
  });

  it("renders bold, italic and inline code", () => {
    const { container } = render(<p>{inline("**b** and *i* and `c`")}</p>);
    expect(container.querySelector("strong")?.textContent).toBe("b");
    expect(container.querySelector("em")?.textContent).toBe("i");
    expect(container.querySelector("code")?.textContent).toBe("c");
  });
});
