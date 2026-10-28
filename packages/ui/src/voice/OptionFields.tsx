"use client";

import type { VoiceOption } from "@wasifyai/client";
import { Checkbox } from "../components/checkbox";
import { Input } from "../components/input";
import { Label } from "../components/label";
import { Select } from "../components/select";
import { Slider } from "../components/slider";

/** Controls for a model's options, made from its descriptor, so a new model's settings need no new
 * screen. A number with bounds is a slider; an enum is a list; empty means "the model's own choice".
 * The app's own controls throughout (ADR-0093): no native select, checkbox or range. */
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
    <fieldset className="grid min-w-0 gap-4 border-0 p-0">
      <legend className="sr-only">Options</legend>
      {options.map((o) => {
        const id = `opt-${o.name}`;
        const v = values[o.name];
        const slider = o.type === "float" && o.min !== null && o.max !== null;
        const hint = o.description ? (
          <p className="m-0 text-muted-foreground text-xs">{o.description}</p>
        ) : null;
        if (o.type === "bool") {
          return (
            <Checkbox
              key={o.name}
              id={id}
              label={o.label}
              hint={o.description || undefined}
              checked={Boolean(v ?? o.default)}
              disabled={disabled}
              onCheckedChange={(c) => onChange(o.name, c)}
            />
          );
        }
        if (slider) {
          return (
            <div key={o.name} className="grid gap-1.5">
              <span aria-hidden="true" className="font-medium text-sm">
                {o.label}
              </span>
              <Slider
                id={id}
                label={o.label}
                min={o.min ?? 0}
                max={o.max ?? 1}
                step={(o.max ?? 1) - (o.min ?? 0) > 5 ? 0.5 : 0.05}
                value={Number(v ?? o.default ?? o.min)}
                disabled={disabled}
                onValueChange={(n) => onChange(o.name, n)}
              />
              {hint}
            </div>
          );
        }
        return (
          <div key={o.name} className="grid gap-1.5">
            <Label htmlFor={id}>{o.label}</Label>
            {o.type === "enum" ? (
              <Select
                id={id}
                value={String(v ?? o.default ?? "")}
                disabled={disabled}
                options={o.values.map((x) => ({ value: x, label: x }))}
                onValueChange={(x) => onChange(o.name, x)}
              />
            ) : o.type === "int" || o.type === "float" ? (
              <Input
                id={id}
                type="number"
                inputMode="numeric"
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
              <Input
                id={id}
                value={String(v ?? "")}
                disabled={disabled}
                onChange={(e) => onChange(o.name, e.target.value || undefined)}
              />
            )}
            {hint}
          </div>
        );
      })}
    </fieldset>
  );
}

/** The few words after "For experts" that say what is inside ("speed, seed"). */
export function expertsSummary(options: VoiceOption[]): string {
  return options.map((o) => o.label.toLowerCase()).join(", ");
}
