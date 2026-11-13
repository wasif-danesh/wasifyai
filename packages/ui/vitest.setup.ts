import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// The chat is a lazy chunk (assistant-ui, streamdown): its first load can take longer than the default 1 s
// wait when the machine is busy, and a test that looks for its text would then fail without a bug.
configure({ asyncUtilTimeout: 5000 });

// jsdom has no layout, so the few browser APIs the chat thread (assistant-ui) reads are stubbed
if (typeof window !== "undefined") {
  class NoopObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  }
  window.ResizeObserver ??= NoopObserver as unknown as typeof ResizeObserver;
  window.IntersectionObserver ??= NoopObserver as unknown as typeof IntersectionObserver;
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  Element.prototype.scrollTo ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
  // Radix's menus and lists hold the pointer
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
}
