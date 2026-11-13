// SPDX-License-Identifier: AGPL-3.0-only
// What the window knows about the engine, from the shell (apps/desktop/src-tauri/src/engine.rs).
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

/** One marker from the installer: which of its steps is running, and how far it is. */
export type InstallProgress = {
  /** "engine" (the first-run install) or an optional component such as "comfyui" */
  component: string;
  step: string;
  label: string;
  /** 1-based, out of `count` */
  index: number;
  count: number;
  bytes_done: number | null;
  bytes_total: number | null;
  /** the installer's latest line of output */
  detail: string | null;
};

export type EngineStatus =
  | { state: "installing"; progress: InstallProgress }
  | { state: "starting"; attempt: number }
  | { state: "ready"; base_url: string; pid: number }
  /** `step` names the install step that failed, when the failure was an install */
  | { state: "failed"; message: string; step: string | null }
  | { state: "stopped" };

/** How far through the whole install it is, 0 to 1: finished steps plus the part of this one. */
export function installFraction(p: InstallProgress): number {
  const within = p.bytes_total ? Math.min(1, (p.bytes_done ?? 0) / p.bytes_total) : 0;
  return Math.min(1, Math.max(0, (p.index - 1 + within) / p.count));
}

export type EngineSession = { base_url: string; token: string; expires_at: number };

const STATUS_EVENT = "engine://status";

export const engineStatus = () => invoke<EngineStatus>("engine_status");
export const engineSession = () => invoke<EngineSession>("engine_session");
export const engineRestart = () => invoke<void>("engine_restart");
export const engineRepair = () => invoke<void>("engine_repair");

/** Calls `fn` with every status change. Returns a function that stops listening. */
export async function onEngineStatus(fn: (s: EngineStatus) => void): Promise<() => void> {
  return listen<EngineStatus>(STATUS_EVENT, (e) => fn(e.payload));
}

/** What the app's own updater found. `not_configured`: this build has no signing key or feed. */
export type UpdateStatus =
  | { state: "not_configured" }
  | { state: "up_to_date" }
  | { state: "available"; version: string; notes: string | null }
  | { state: "failed"; message: string };

export const updateCheck = () => invoke<UpdateStatus>("update_check");
export const updateInstall = () => invoke<void>("update_install");

/** An optional part the person can add (the image engine, the language engine): `components.ts` asks the engine. */
export type ComponentStatus =
  | { state: "unsupported"; reason: string }
  | { state: "not_installed"; needs_bytes: number }
  | { state: "installing"; progress: InstallProgress }
  /** `accelerator`: what the engine found to run on: "mps" (Apple GPU), "cuda" or "cpu" */
  | { state: "installed"; version: string; accelerator: string }
  | { state: "failed"; message: string; step: string | null };

export const COMFYUI = "comfyui";
export const LLAMACPP = "llamacpp";

/** "4.3 GB", "620 MB": sizes in sentences, in decimal units like the rest of the app. */
export function humanBytes(bytes: number): string {
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
  return `${Math.max(1, Math.round(bytes / 1_000_000))} MB`;
}
