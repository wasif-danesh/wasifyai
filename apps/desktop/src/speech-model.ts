// SPDX-License-Identifier: AGPL-3.0-only
// Getting a speech model (the one for dictation, or the voice for read aloud; ADR-0083, decision 5) from the chat's setup card. The card has already shown what it is,
// where it comes from and how big it is, and the person pressed the download button: this asks the engine for it with the same
// confirmation the Models screen sends (the files and the bytes), and reports how far it is until it is done.
import { type ModelsApi, downloadFraction } from "./models";

const POLL_MS = 500;

export async function getSpeechModel(
  models: Pick<ModelsApi, "overview" | "start" | "download">,
  modelId: string,
  onProgress: (fraction: number) => void,
  wait: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
): Promise<void> {
  const entry = (await models.overview()).models.find((m) => m.id === modelId);
  if (!entry) throw new Error("That speech model is not one this app knows.");
  if (entry.status === "ready") return;
  let state = await models.start(entry);
  while (state.status === "running") {
    onProgress(downloadFraction(state));
    await wait(POLL_MS);
    state = await models.download(state.id);
  }
  if (state.status !== "done") {
    throw new Error(state.error || "The speech model could not be downloaded. Try again.");
  }
  onProgress(1);
}
