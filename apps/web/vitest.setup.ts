process.env.AUTH_MODE = "stub"; // tests run without sign-in unless a test turns it on
import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// The chat is a lazy chunk (assistant-ui, streamdown): its first load can take longer than the default 1 s
// wait when the machine is busy, and a test that looks for its text would then fail without a bug.
configure({ asyncUtilTimeout: 5000 });

// the side panel asks whether the screen is narrow
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

// Radix (select, dialog, menus) needs a few browser APIs that jsdom does not have.
if (typeof Element !== "undefined") {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.setPointerCapture ??= () => {};
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
  // the chat thread (assistant-ui) scrolls its viewport and watches it
  Element.prototype.scrollTo ??= () => {};
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  globalThis.IntersectionObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  } as unknown as typeof IntersectionObserver;
}
