import { downloadDir, join } from "@tauri-apps/api/path";
import { save } from "@tauri-apps/plugin-dialog";
// SPDX-License-Identifier: AGPL-3.0-only
// "Save a copy" in this window: the system's own Save As box (Tauri's dialog plugin) says where, and the
// engine writes the file there. The window cannot download a file by itself, and it never picks a folder
// for the person: the box opens in the system's Downloads folder, which the system names (it can be moved).
import { HttpError, errorMessage } from "@wasifyai/client";
import type { SaveAs } from "@wasifyai/ui";
import { transport } from "./api";

export const saveAs: SaveAs = {
  async choose(suggestedName) {
    let defaultPath = suggestedName;
    try {
      defaultPath = await join(await downloadDir(), suggestedName);
    } catch {
      // no known Downloads folder: the box opens where the system chooses
    }
    return await save({ defaultPath, title: "Save a copy" });
  },

  async write(path, data) {
    const form = new FormData();
    form.append("path", path);
    form.append("file", data, "file");
    const res = await transport.fetch("/desktop/save", { method: "POST", body: form });
    if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
    return (await res.json()) as { name: string; path: string };
  },
};
