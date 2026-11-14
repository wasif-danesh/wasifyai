// SPDX-License-Identifier: AGPL-3.0-only
// Code (ADR-0101): the shared screens on this window's engine, with the computer's own folder window.
import { open } from "@tauri-apps/plugin-dialog";
import { Code } from "@wasifyai/ui";
import { code } from "../code";
import type { Route } from "../router";

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
  return (
    <Code
      api={code}
      pickFolder={pickFolder}
      onOpenSetup={() => go("settings")}
      onOpenKeys={() => go("settings")}
    />
  );
}
