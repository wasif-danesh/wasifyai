"use client";
// The Labs switch for the new chat (ADR-0082 decision 11): the old chat stays the default until the new one has parity. The
// choice is a convenience kept in the browser or the webview, never required: if storage is blocked the old chat is used.
import { useCallback, useSyncExternalStore } from "react";

export const CHAT_NEXT_KEY = "wasifyai.labs.chat-next";
const CHANGED = "wasifyai:labs-changed";

export function readChatNext(): boolean {
  try {
    return localStorage.getItem(CHAT_NEXT_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeChatNext(on: boolean): void {
  try {
    if (on) localStorage.setItem(CHAT_NEXT_KEY, "1");
    else localStorage.removeItem(CHAT_NEXT_KEY);
  } catch {
    // forgotten
  }
  window.dispatchEvent(new Event(CHANGED));
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(CHANGED, cb);
  window.addEventListener("storage", cb); // another window changed it
  return () => {
    window.removeEventListener(CHANGED, cb);
    window.removeEventListener("storage", cb);
  };
}

/** Whether the person turned the new chat on, and a way to change it. The server and the first paint say no. */
export function useChatNext(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, readChatNext, () => false);
  const set = useCallback((next: boolean) => writeChatNext(next), []);
  return [on, set];
}
