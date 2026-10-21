// SPDX-License-Identifier: AGPL-3.0-only
// A router small enough to need no library: the window has a handful of screens, addressed by the URL
// hash (which a webview keeps across reloads and needs no server for).
import { useCallback, useEffect, useState } from "react";

export type Route =
  | "home"
  | "create"
  | "edit"
  | "reference"
  | "inpaint"
  | "library"
  | "models"
  | "settings"
  | "notebooks"
  | "notebook"
  | "speak"
  | "transcribe"
  | "voices"
  | "music"
  | "tracks"
  | "lyrics"
  | "separate"
  | "convert"
  | "speechedit"
  | "lipsync"
  | "dub"
  | "audiobook"
  | "video"
  | "animate"
  | "extend"
  | "videobuilder"
  | "model3d"
  | "videos";

const PATHS: Record<Route, string> = {
  home: "/",
  create: "/images/create",
  edit: "/images/edit",
  reference: "/images/reference",
  inpaint: "/images/inpaint",
  library: "/library",
  models: "/models",
  settings: "/settings",
  notebooks: "/notebooks",
  notebook: "/notebooks/new", // the draft; a saved notebook is `/notebooks/<id>`
  speak: "/voice/speak",
  transcribe: "/voice/transcribe",
  voices: "/voice/voices",
  music: "/music/create",
  tracks: "/music/library",
  lyrics: "/music/lyrics",
  separate: "/music/separate",
  convert: "/voice/convert",
  speechedit: "/voice/edit-speech",
  lipsync: "/voice/lip-sync",
  dub: "/voice/dub",
  audiobook: "/voice/audiobook",
  video: "/video/create",
  animate: "/video/animate",
  extend: "/video/extend",
  videobuilder: "/video/builder",
  model3d: "/images/3d",
  videos: "/video/library",
};

/** The id in the draft address: a notebook that is not saved yet. */
export const NEW_NOTEBOOK = "new";

/** The notebook a hash opens (`#/notebooks/<id>`, or `new` for a draft), or null. */
export function parseNotebook(hash: string): string | null {
  const path = hash.replace(/^#/, "").split("?")[0] ?? "";
  const m = /^\/notebooks\/([A-Za-z0-9-]{1,64})$/.exec(path);
  return m?.[1] ?? null;
}

export function notebookPath(id: string | null): string {
  return id ? `/notebooks/${id}` : "/notebooks";
}

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
  if (parseNotebook(hash)) return "notebook";
  const found = (Object.keys(PATHS) as Route[]).find((r) => PATHS[r] === path);
  return found ?? "home";
}

export type RouteState = {
  route: Route;
  go: (r: Route) => void;
  /** the saved conversation open on the home screen */
  conversation: string | null;
  /** a key that changes only when the person navigates (not when a new chat or notebook gets its id) */
  key: number;
  /** give the open chat its address without reloading it */
  adopt: (id: string) => void;
  /** the notebook open (`new` for a draft) */
  notebook: string | null;
  /** give a draft notebook its address without reloading it */
  adoptNotebook: (id: string) => void;
};

function readHash() {
  return {
    route: parseHash(window.location.hash),
    conversation: parseConversation(window.location.hash),
    notebook: parseNotebook(window.location.hash),
  };
}

export function useRoute(): RouteState {
  const [state, setState] = useState(() => ({ ...readHash(), key: 0 }));
  useEffect(() => {
    const onChange = () => setState((s) => ({ ...readHash(), key: s.key + 1 }));
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
  const adoptNotebook = useCallback((id: string) => {
    window.history.replaceState(null, "", `#${notebookPath(id)}`);
    setState((s) => ({ ...s, notebook: id }));
  }, []);
  return {
    route: state.route,
    go,
    conversation: state.conversation,
    key: state.key,
    adopt,
    notebook: state.notebook,
    adoptNotebook,
  };
}

/** Open a saved conversation, or start a new chat with null. */
export function openChat(id: string | null): void {
  window.location.hash = chatPath(id);
}

/** Open a notebook, a new draft with null... */
export function openNotebook(id: string | null): void {
  window.location.hash = id ? notebookPath(id) : routePath("notebooks");
}

/** A new notebook: a draft that is saved when its first source is added. */
export function newNotebook(): void {
  window.location.hash = notebookPath(NEW_NOTEBOOK);
}
