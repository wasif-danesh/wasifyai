"use client";

import type { VoiceOption } from "@wasifyai/client";
import { Label } from "../components/label";

/** Controls for a model's options, made from its descriptor, so a new model's settings need no new
 * screen. A number with bounds is a slider; an enum is a list; empty means "the model's own choice". */
export function OptionFields({
  options,
  values,
  onChange,
  disabled,
}: {
  options: VoiceOption[];
  values: Record<string, unknown>;
  onChange: (name: string, value: unknown) => void;
  disabled?: boolean;
}) {
  if (options.length === 0) return null;
  return (
    <fieldset className="grid min-w-0 gap-3 border-0 p-0">
      <legend className="sr-only">Options</legend>
      {options.map((o) => {
        const id = `opt-${o.name}`;
        const v = values[o.name];
        const slider = o.type === "float" && o.min !== null && o.max !== null;
        return (
          <div key={o.name} className="grid gap-1.5">
            <Label htmlFor={id}>
              {o.label}
              {slider ? (
                <span className="ms-auto font-normal text-muted-foreground">
                  {String(v ?? o.default)}
                </span>
              ) : null}
            </Label>
            {o.type === "bool" ? (
              <input
                id={id}
                type="checkbox"
                className="size-4"
                checked={Boolean(v ?? o.default)}
                disabled={disabled}
                onChange={(e) => onChange(o.name, e.target.checked)}
              />
            ) : o.type === "enum" ? (
              <select
                id={id}
                className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                value={String(v ?? o.default ?? "")}
                disabled={disabled}
                onChange={(e) => onChange(o.name, e.target.value)}
              >
                {o.values.map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </select>
            ) : slider ? (
              <input
                id={id}
                type="range"
                min={o.min ?? 0}
                max={o.max ?? 1}
                step={(o.max ?? 1) - (o.min ?? 0) > 5 ? 0.5 : 0.05}
                value={Number(v ?? o.default ?? o.min)}
                disabled={disabled}
                onChange={(e) => onChange(o.name, Number(e.target.value))}
              />
            ) : o.type === "int" || o.type === "float" ? (
              <input
                id={id}
                type="number"
                inputMode="numeric"
                className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                min={o.min ?? undefined}
                max={o.max ?? undefined}
                step={o.type === "int" ? 1 : "any"}
                placeholder="the model's own choice"
                value={v === undefined ? "" : String(v)}
                disabled={disabled}
                onChange={(e) =>
                  onChange(o.name, e.target.value === "" ? undefined : Number(e.target.value))
                }
              />
            ) : (
              <input
                id={id}
                className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
                value={String(v ?? "")}
                disabled={disabled}
                onChange={(e) => onChange(o.name, e.target.value || undefined)}
              />
            )}
            {o.description ? (
              <p className="text-muted-foreground text-xs">{o.description}</p>
            ) : null}
          </div>
        );
      })}
    </fieldset>
  );
}
