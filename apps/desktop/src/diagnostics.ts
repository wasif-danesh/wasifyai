// SPDX-License-Identifier: AGPL-3.0-only
// Save diagnostics (stage O2): the system's Save As box says where, and the engine writes one zip there
// with the logs' ends, the parts' states, the last actions and the computer's figures (never content).
import { downloadDir, join } from "@tauri-apps/api/path";
import { save } from "@tauri-apps/plugin-dialog";
import { HttpError, errorMessage } from "@wasifyai/client";
import { transport } from "./api";

export type SavedDiagnostics = { name: string; path: string; bytes: number };

/** Ask where, then have the engine write the zip; null when the person closed the box. */
export async function saveDiagnostics(): Promise<SavedDiagnostics | null> {
  const named = await transport.fetch("/desktop/diagnostics/name");
  if (!named.ok) throw new HttpError(named.status, await errorMessage(named));
  const { name } = (await named.json()) as { name: string };
  let defaultPath = name;
  try {
    defaultPath = await join(await downloadDir(), name);
  } catch {
    // no known Downloads folder: the box opens where the system chooses
  }
  const path = await save({
    defaultPath,
    title: "Save diagnostics",
    filters: [{ name: "Zip", extensions: ["zip"] }],
  });
  if (!path) return null;
  const res = await transport.fetch("/desktop/diagnostics", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
  return (await res.json()) as SavedDiagnostics;
}
