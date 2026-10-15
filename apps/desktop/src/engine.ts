// SPDX-License-Identifier: AGPL-3.0-only
// What the window knows about the engine, from the shell (apps/desktop/src-tauri/src/engine.rs).
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export type EngineStatus =
  | { state: "starting"; attempt: number }
  | { state: "ready"; base_url: string; pid: number }
  | { state: "failed"; message: string }
  | { state: "stopped" };

export type EngineSession = { base_url: string; token: string; expires_at: number };

const STATUS_EVENT = "engine://status";

export const engineStatus = () => invoke<EngineStatus>("engine_status");
export const engineSession = () => invoke<EngineSession>("engine_session");
export const engineRestart = () => invoke<void>("engine_restart");

/** Calls `fn` with every status change. Returns a function that stops listening. */
export async function onEngineStatus(fn: (s: EngineStatus) => void): Promise<() => void> {
  return listen<EngineStatus>(STATUS_EVENT, (e) => fn(e.payload));
}
