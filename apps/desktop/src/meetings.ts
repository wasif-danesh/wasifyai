// SPDX-License-Identifier: AGPL-3.0-only
// Meetings (ADR-0108): the shared API (packages/client) on the window's transport, and the shell's
// recorder (src-tauri/src/recorder.rs, stage MT2): the microphone and the computer's sound in one file.
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { createMeetingsApi } from "@wasifyai/client";
import type { MeetingRecorder, RecordState, RecordedMeeting } from "@wasifyai/ui";
import { transport } from "./api";

export const meetings = createMeetingsApi(transport);

// Stop in the menu bar finishes the recording in the shell and tells the window. One told while no
// Record screen listens is kept until one does, so the meeting is still made when it opens.
let pending: RecordedMeeting[] = [];
const hearing = new Set<(r: RecordedMeeting) => void>();
const failing = new Set<(p: string) => void>();
let listening = false;

function listenOnce() {
  if (listening) return;
  listening = true;
  void listen<RecordedMeeting>("meeting-recorded", (e) => {
    if (hearing.size) for (const told of hearing) told(e.payload);
    else pending.push(e.payload);
  }).catch(() => {});
  void listen<string>("meeting-record-failed", (e) => {
    for (const told of failing) told(e.payload);
  }).catch(() => {});
}

/** The recorder; `onStopped` is told when the menu bar's Stop finished a recording (to open Record). */
export const recorder: MeetingRecorder = {
  state: () => invoke<RecordState>("meeting_record_state"),
  start: () => invoke<RecordState>("meeting_record_start"),
  stop: () => invoke<RecordedMeeting>("meeting_record_stop"),
  onRecorded: (told) => {
    listenOnce();
    hearing.add(told);
    const waiting = pending;
    pending = [];
    for (const r of waiting) told(r);
    return () => void hearing.delete(told);
  },
  onFailed: (told) => {
    listenOnce();
    failing.add(told);
    return () => void failing.delete(told);
  },
};

/** Told when the menu bar's Stop finished a recording, wherever the window is (it opens Record). */
export function onStoppedFromMenu(told: () => void): () => void {
  listenOnce();
  const stop = listen("meeting-recorded", () => told());
  return () => void stop.then((off) => off()).catch(() => {});
}
