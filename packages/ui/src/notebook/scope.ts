// Which sources a question is asked of: the ticks of the sources tree. Everything is ticked until a
// person unticks something, so a source added later counts without a click. The shape of the logic
// (a folder is ticked when everything under it is, partly when some of it is) follows SurfSense's
// `scope-state.ts` (Apache-2.0, commit 622c1ded8), written afresh for this tree.
import type { NotebookFolder, NotebookSource } from "@wasifyai/client";

export type Tick = "all" | "some" | "none";

/** The ids of every folder at or under `folderId`. */
export function folderTree(folders: NotebookFolder[], folderId: string): Set<string> {
  const out = new Set<string>([folderId]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const f of folders) {
      if (f.parent_id && out.has(f.parent_id) && !out.has(f.id)) {
        out.add(f.id);
        grew = true;
      }
    }
  }
  return out;
}

/** The sources under a folder (and its subfolders). */
export function sourcesUnder(
  folders: NotebookFolder[],
  sources: NotebookSource[],
  folderId: string,
): NotebookSource[] {
  const tree = folderTree(folders, folderId);
  return sources.filter((s) => s.folder_id !== null && tree.has(s.folder_id));
}

export function tickOf(ids: string[], unticked: Set<string>): Tick {
  if (ids.length === 0) return "none";
  const off = ids.filter((id) => unticked.has(id)).length;
  if (off === 0) return "all";
  return off === ids.length ? "none" : "some";
}

/** What clicking a tick does: a mixed or ticked group is unticked, an unticked one is ticked. */
export function toggle(ids: string[], unticked: Set<string>): Set<string> {
  const next = new Set(unticked);
  if (tickOf(ids, unticked) === "none") for (const id of ids) next.delete(id);
  else for (const id of ids) next.add(id);
  return next;
}

/**
 * What to send as `document_ids`: undefined when nothing is unticked (the engine searches every
 * source that is ready, including ones that arrive meanwhile), otherwise the ticked ones that are
 * ready, which may be empty.
 */
export function scopeIds(sources: NotebookSource[], unticked: Set<string>): string[] | undefined {
  if (unticked.size === 0 || !sources.some((s) => unticked.has(s.id))) return undefined;
  return sources.filter((s) => s.status === "ready" && !unticked.has(s.id)).map((s) => s.id);
}

/** "12 of 14 sources" for the chat box and the header, with what is being read or could not be read. */
export function scopeLabel(sources: NotebookSource[], unticked: Set<string>): string {
  const ready = sources.filter((s) => s.status === "ready");
  const used = ready.filter((s) => !unticked.has(s.id)).length;
  const reading = sources.filter((s) => s.status === "pending" || s.status === "processing").length;
  const failed = sources.filter((s) => s.status === "failed").length;
  const notes = [
    reading > 0 ? `${reading} being read` : "",
    failed > 0 ? `${failed} could not be read` : "",
  ].filter(Boolean);
  if (ready.length === 0 && sources.length > 0)
    return notes.length ? notes.join(", ") : "No sources";
  const base =
    used === ready.length
      ? `${used} source${used === 1 ? "" : "s"}`
      : `${used} of ${ready.length} sources`;
  return notes.length ? `${base}, ${notes.join(", ")}` : base;
}

/**
 * Why a question or an output cannot be made when no source is ready, or null when one is. "Still being read"
 * is only said while something is being read: when every source failed, saying so and how to go on is the
 * honest answer (a person who sees "still being read" waits for something that will never finish).
 */
export function noReadySourceReason(sources: NotebookSource[]): string | null {
  if (sources.length === 0 || sources.some((s) => s.status === "ready")) return null;
  if (sources.some((s) => s.status === "pending" || s.status === "processing"))
    return "Your sources are still being read.";
  if (sources.some((s) => s.status === "failed"))
    return "None of your sources could be read. Open one to see why, then read it again.";
  return "Reading was stopped. Read your sources again to ask about them.";
}
