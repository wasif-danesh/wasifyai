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

/** The route a hash names; anything unknown is the home screen. */
export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "").split("?")[0] || "/";
  const found = (Object.keys(PATHS) as Route[]).find((r) => PATHS[r] === path);
  return found ?? "home";
}

export function useRoute(): [Route, (r: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const go = useCallback((r: Route) => {
    window.location.hash = routePath(r);
  }, []);
  return [route, go];
}
