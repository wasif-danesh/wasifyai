"use client";
// One field of a Motion graphics form, built from what the engine said about it: on the template form and
// in the scene editor.
import type { FieldInfo, TemplateCatalogue } from "@wasifyai/client";
import { useId } from "react";
import { cn } from "../cn";
import { Chip } from "../components/chip";
import { chips, field, fieldLabel, hint } from "../styles";
import { lengths } from "./slots";

export const INPUT =
  "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30";

const SHAPE_HINTS: Record<string, string> = { landscape: "16:9", portrait: "9:16", square: "1:1" };

export type FieldProps = {
  info: FieldInfo;
  value: string;
  catalogue: TemplateCatalogue | null;
  onChange: (value: string) => void;
};

/** One field of the form, built from what the engine said about it. */
export function FormField({ info, value, catalogue, onChange }: FieldProps) {
  const id = useId();
  const optional = info.required ? null : (
    <span className="font-normal text-muted-foreground"> (optional)</span>
  );
  if (info.kind === "text") {
    return (
      <div className={field}>
        <label className={fieldLabel} htmlFor={id}>
          {info.label}
          {optional}
        </label>
        <input
          id={id}
          className={INPUT}
          value={value}
          maxLength={info.max_chars}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    );
  }
  if (info.kind === "longtext" || info.kind === "lines" || info.kind === "rows") {
    return (
      <div className={field}>
        <label className={fieldLabel} htmlFor={id}>
          {info.label}
          {optional}
        </label>
        <textarea
          id={id}
          className={cn(INPUT, "min-h-24 font-[inherit]")}
          rows={info.kind === "longtext" ? 3 : 6}
          value={value}
          maxLength={info.kind === "longtext" ? info.max_chars : undefined}
          spellCheck={info.kind !== "rows"}
          onChange={(e) => onChange(e.target.value)}
        />
        {info.hint ? <p className={hint}>{info.hint}</p> : null}
      </div>
    );
  }
  if (info.kind === "seconds") {
    return (
      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>{info.label}</legend>
        <div className={cn(chips, "items-center")}>
          {lengths(info.min, info.max).map((n) => (
            <Chip key={n} aria-pressed={Number(value) === n} onClick={() => onChange(String(n))}>
              {n} seconds
            </Chip>
          ))}
          <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
            or
            <input
              id={id}
              type="number"
              inputMode="numeric"
              min={info.min}
              max={info.max}
              aria-label={`${info.label} in seconds`}
              className={cn(INPUT, "w-20 py-1")}
              value={value}
              onChange={(e) => onChange(e.target.value)}
            />
            seconds
          </label>
        </div>
        <p className={hint}>
          From {info.min} to {info.max} seconds.
        </p>
      </fieldset>
    );
  }
  return (
    <fieldset className={cn(field, "m-0 border-0 p-0")}>
      <legend className={cn(fieldLabel, "mb-1.5")}>{info.label}</legend>
      <div className={chips}>
        {info.choices.map((c) => {
          const colours = info.id === "theme" ? catalogue?.themes[c.id as "midnight"] : undefined;
          return (
            <Chip key={c.id} aria-pressed={value === c.id} onClick={() => onChange(c.id)}>
              {colours ? (
                <span
                  aria-hidden="true"
                  className="me-1.5 inline-block size-3 rounded-full border align-middle"
                  style={{
                    background: `linear-gradient(135deg, ${colours.from}, ${colours.accent})`,
                  }}
                />
              ) : null}
              {c.label}
              {info.id === "shape" && SHAPE_HINTS[c.id] ? (
                <span className="opacity-85"> {SHAPE_HINTS[c.id]}</span>
              ) : null}
            </Chip>
          );
        })}
      </div>
    </fieldset>
  );
}
