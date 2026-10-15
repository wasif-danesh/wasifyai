// SPDX-License-Identifier: AGPL-3.0-only
// A router small enough to need no library: the window has a handful of screens, addressed by the URL
// hash (which a webview keeps across reloads and needs no server for).
import { useCallback, useEffect, useState } from "react";

export type Route = "home" | "create" | "edit" | "library" | "models" | "settings";

const PATHS: Record<Route, string> = {
  home: "/",
  create: "/images/create",
  edit: "/images/edit",
  library: "/library",
  models: "/models",
  settings: "/settings",
};

export function routePath(route: Route): string {
  return PATHS[route];
}

/** The saved conversation a hash opens (`#/chat/<id>`), or null: a new chat. */
export function parseConversation(hash: string): string | null {
  const path = hash.replace(/^#/, "").split("?")[0] ?? "";
  const m = /^\/chat\/([A-Za-z0-9-]{1,64})$/.exec(path);
  return m?.[1] ?? null;
}

/** Where a conversation is opened (the home screen is the chat). */
export function chatPath(id: string | null): string {
  return id ? `/chat/${id}` : "/";
}

/** The route a hash names; anything unknown is the home screen. */
export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "").split("?")[0] || "/";
  if (parseConversation(hash)) return "home";
  const found = (Object.keys(PATHS) as Route[]).find((r) => PATHS[r] === path);
  return found ?? "home";
}

/**
 * The current route, a way to go to one, the open conversation, a key that changes only when the person
 * navigates (not when a new chat gets its id), and `adopt`, which gives the open chat its address without
 * reloading it.
 */
export function useRoute(): [
  Route,
  (r: Route) => void,
  string | null,
  number,
  (id: string) => void,
] {
  const [state, setState] = useState(() => ({
    route: parseHash(window.location.hash),
    conversation: parseConversation(window.location.hash),
    key: 0,
  }));
  useEffect(() => {
    const onChange = () =>
      setState((s) => ({
        route: parseHash(window.location.hash),
        conversation: parseConversation(window.location.hash),
        key: s.key + 1,
      }));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const go = useCallback((r: Route) => {
    window.location.hash = routePath(r);
  }, []);
  const adopt = useCallback((id: string) => {
    window.history.replaceState(null, "", `#${chatPath(id)}`); // no hashchange: the chat stays as it is
    setState((s) => ({ ...s, conversation: id }));
  }, []);
  return [state.route, go, state.conversation, state.key, adopt];
}

/** Open a saved conversation, or start a new chat with null. */
export function openChat(id: string | null): void {
  window.location.hash = chatPath(id);
}
