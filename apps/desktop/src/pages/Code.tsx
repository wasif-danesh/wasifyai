// SPDX-License-Identifier: AGPL-3.0-only
// Code (ADR-0101): the shared screens on this window's engine, with the computer's own folder window. A
// session has an address of its own (`#/code/<id>`), so it is still open after a reload and Back leaves it.
import { open } from "@tauri-apps/plugin-dialog";
import { Code } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { code } from "../code";
import { type Route, codePath, parseCodeSession } from "../router";

/** The folder a person chose in the computer's folder window, or null when they closed it. */
export async function pickFolder(): Promise<string | null> {
  const chosen = await open({
    directory: true,
    multiple: false,
    title: "Choose a project's folder",
  });
  return typeof chosen === "string" ? chosen : null;
}

export function CodePage({ go }: { go: (r: Route) => void }) {
  const [openId, setOpenId] = useState(() => parseCodeSession(window.location.hash));
  useEffect(() => {
    const onChange = () => setOpenId(parseCodeSession(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return (
    <Code
      api={code}
      pickFolder={pickFolder}
      onOpenSetup={() => go("settings")}
      onOpenKeys={() => go("settings")}
      openId={openId}
      onOpenChange={(id) => {
        window.location.hash = codePath(id);
      }}
    />
  );
}
