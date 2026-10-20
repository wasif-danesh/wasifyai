// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { externalAddress, openExternalLinks } from "./external-links";

function page(html: string): HTMLElement {
  document.body.innerHTML = html;
  return document.body;
}

describe("links that ask for a new window", () => {
  it("hands an ordinary web address to the shell, and keeps the window where it is", () => {
    const open = vi.fn(async () => {});
    const off = openExternalLinks(document, open);
    page(
      '<a id="a" target="_blank" href="https://example.com/x?y=1"><span id="s">source</span></a>',
    );
    const click = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    document.getElementById("s")?.dispatchEvent(click);
    expect(open).toHaveBeenCalledWith("https://example.com/x?y=1");
    expect(click.defaultPrevented).toBe(true);
    off();
  });

  it("leaves everything else alone", () => {
    page(
      '<a id="same" href="https://example.com/">same</a><a id="js" target="_blank" href="javascript:alert(1)">js</a>' +
        '<a id="file" target="_blank" href="file:///etc/passwd">file</a><button id="b">b</button>',
    );
    expect(externalAddress(document.getElementById("same"))).toBeNull(); // opens in place: not our business
    expect(externalAddress(document.getElementById("js"))).toBeNull();
    expect(externalAddress(document.getElementById("file"))).toBeNull();
    expect(externalAddress(document.getElementById("b"))).toBeNull();
    expect(externalAddress(null)).toBeNull();
  });

  it("does nothing for a click something else already handled, or a right click", () => {
    const open = vi.fn(async () => {});
    const off = openExternalLinks(document, open);
    page('<a id="a" target="_blank" href="https://example.com/">x</a>');
    const handled = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    handled.preventDefault();
    document.getElementById("a")?.dispatchEvent(handled);
    document
      .getElementById("a")
      ?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 2 }));
    expect(open).not.toHaveBeenCalled();
    off();
  });
});
