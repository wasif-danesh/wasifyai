// The words of a project as the form holds them (text only) and as the engine takes them.
import type { BuilderSlots, TemplateInfo } from "@wasifyai/client";

/** What a form field holds: always text, even for numbers, lines and rows. */
export type Draft = Record<string, string>;

type Row = { label: string; value: string };

/** The starting values of a new project: the defaults the engine named, as text. */
export function blankDraft(template: TemplateInfo): Draft {
  const out: Draft = {};
  for (const f of template.fields) out[f.id] = f.default === null ? "" : String(f.default);
  return out;
}

/** A saved project's slots as form text: rows as "label, value" lines, lines one per line. */
export function toDraft(template: TemplateInfo, slots: BuilderSlots): Draft {
  const out = blankDraft(template);
  for (const f of template.fields) {
    const value = slots[f.id];
    if (value === undefined) continue;
    if (f.kind === "rows" && Array.isArray(value)) {
      out[f.id] = (value as Row[]).map((r) => `${r.label}, ${r.value}`).join("\n");
    } else if (f.kind === "lines" && Array.isArray(value)) {
      out[f.id] = (value as string[]).join("\n");
    } else {
      out[f.id] = String(value);
    }
  }
  return out;
}

/** What goes to the engine: the typed text, with the length as a number. Nothing is rewritten. */
export function fromDraft(template: TemplateInfo, draft: Draft): BuilderSlots {
  const out: BuilderSlots = {};
  for (const f of template.fields) {
    const text = draft[f.id] ?? "";
    out[f.id] = f.kind === "seconds" ? Number(text) : f.kind === "text" ? text.trim() : text;
  }
  return out;
}

/** The first field that must be filled in and is empty: the form's "can this be made yet". */
export function missing(template: TemplateInfo, draft: Draft): string | null {
  for (const f of template.fields) {
    if (f.required && !(draft[f.id] ?? "").trim()) return f.label;
  }
  return null;
}

/** The lengths offered as buttons: a few spread through the range, and the current one. */
export function lengths(min: number, max: number, current: number): number[] {
  const steps = [2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 30, 48].filter((n) => n >= min && n <= max);
  const all = steps.includes(current) || Number.isNaN(current) ? steps : [...steps, current];
  return all.sort((a, b) => a - b);
}
