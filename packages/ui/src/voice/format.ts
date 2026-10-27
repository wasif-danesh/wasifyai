import type { CommercialUse, ModelState, VoiceInfo, VoiceModelInfo } from "@wasifyai/client";

/** "1:05", "0:07": a length as a person reads it. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export const STATE_TEXT: Record<ModelState, string> = {
  ready: "Ready",
  needs_runtime: "Needs the speech runtime",
  can_install: "Not on this computer yet",
  not_available: "Not available on this computer",
};

export const COMMERCIAL_TEXT: Record<CommercialUse, string> = {
  yes: "Commercial use allowed",
  conditional: "Commercial use with conditions",
  no: "Not for commercial use",
  unreviewed: "Licence not reviewed",
};

/** What a model's state means for this model: a model on the image engine needs that, not speech. */
export function stateText(m: VoiceModelInfo): string {
  if (m.state === "needs_runtime" && m.engine === "comfyui") return "Needs the image engine";
  if (m.state === "needs_runtime" && m.engine === "sidecar") return "Needs the lip sync engine";
  return STATE_TEXT[m.state];
}

/** The text of one choice in the model list. */
export function modelOption(m: VoiceModelInfo, task: string): string {
  const tags = [m.recommended.includes(task as never) ? "recommended" : null];
  if (m.engine === "remote") tags.push("hosted");
  if (m.commercial_use === "no" || m.commercial_use === "unreviewed")
    tags.push("not for commercial use");
  if (m.state !== "ready") tags.push(stateText(m).toLowerCase());
  const shown = tags.filter(Boolean);
  return shown.length ? `${m.title} (${shown.join(", ")})` : m.title;
}

/** The model to show first: the person's last choice if it is still there, else the recommended
 * one that is ready, else the recommended one, else the first. */
export function pickModel(models: VoiceModelInfo[], task: string, last?: string | null) {
  return (
    models.find((m) => m.id === last) ??
    models.find((m) => m.recommended.includes(task as never) && m.state === "ready") ??
    models.find((m) => m.recommended.includes(task as never)) ??
    models[0] ??
    null
  );
}

const LANGUAGE: Record<string, string> = {
  "en-us": "American English",
  "en-gb": "British English",
};

/** Voices grouped for a list: by language, then as the model gives them. */
export function groupVoices(voices: VoiceInfo[]): { label: string; voices: VoiceInfo[] }[] {
  const out = new Map<string, VoiceInfo[]>();
  for (const v of voices) {
    const key = LANGUAGE[v.language] ?? (v.language || "Voices");
    out.set(key, [...(out.get(key) ?? []), v]);
  }
  return [...out].map(([label, list]) => ({ label, voices: list }));
}

export const voiceLabel = (v: VoiceInfo) => `${v.label}${v.gender ? ` (${v.gender})` : ""}`;

/** What the person is told about a model's cost, from what was measured. */
export function costLine(m: VoiceModelInfo): string {
  const bits: string[] = [];
  const { speed_x, memory_gb } = m.measured;
  if (speed_x)
    bits.push(
      speed_x >= 10
        ? `about ${Math.round(speed_x)}× faster than real time`
        : `${speed_x}× real time`,
    );
  if (memory_gb) bits.push(`${memory_gb} GB of memory while loaded`);
  return bits.join(", ");
}

/** "1 minute", "3 minutes": a span of seconds as whole minutes, never less than one. */
export function minutesText(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
}
