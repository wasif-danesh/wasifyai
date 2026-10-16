"use client";

import type { VoiceModelInfo, VoiceTask } from "@wasifyai/client";
import { cn } from "../cn";
import { Label } from "../components/label";
import { formatBytes } from "../notebook/format";
import { COMMERCIAL_TEXT, STATE_TEXT, costLine, modelOption } from "./format";

/**
 * The model list for a task, built from the engine's descriptors (ADR-0066): every model it knows is
 * there, with whether it can be used now, and a line under the list says what the chosen one is, what
 * it costs and which licence its weights carry. A model that is not for commercial use says so.
 */
export function ModelPicker({
  models,
  task,
  value,
  onChange,
  onGetModel,
  disabled,
}: {
  models: VoiceModelInfo[];
  task: VoiceTask;
  value: string | null;
  onChange: (id: string) => void;
  /** open the Models panel (a missing model is fetched there, after the person sees its size) */
  onGetModel?: (id: string) => void;
  disabled?: boolean;
}) {
  const chosen = models.find((m) => m.id === value) ?? null;
  const warn = chosen && (chosen.commercial_use === "no" || chosen.commercial_use === "unreviewed");
  return (
    <div className="grid gap-2">
      <Label htmlFor={`model-${task}`}>Model</Label>
      <select
        id={`model-${task}`}
        className="h-10 w-full rounded-md border border-input bg-transparent px-3 text-sm"
        value={value ?? ""}
        disabled={disabled || models.length === 0}
        onChange={(e) => onChange(e.target.value)}
      >
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {modelOption(m, task)}
          </option>
        ))}
      </select>
      {chosen ? (
        <div className="grid gap-1 text-muted-foreground text-sm" data-testid="model-details">
          <p>
            {chosen.licence}. {costLine(chosen)}
          </p>
          <p className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 text-xs",
                warn ? "border-warn/40 bg-warn/10 text-foreground" : "border-ok/30",
              )}
            >
              {COMMERCIAL_TEXT[chosen.commercial_use]}
            </span>
            <a
              className="underline underline-offset-4"
              href={chosen.licence_evidence}
              target="_blank"
              rel="noreferrer"
            >
              Licence
            </a>
            {chosen.state !== "ready" ? (
              <output>
                {STATE_TEXT[chosen.state]}
                {chosen.state === "can_install" ? ` (${formatBytes(chosen.bytes_missing)})` : ""}.
                {onGetModel && chosen.state === "can_install" ? (
                  <>
                    {" "}
                    <button
                      type="button"
                      className="underline underline-offset-4"
                      onClick={() => onGetModel(chosen.id)}
                    >
                      Get it in Models
                    </button>
                  </>
                ) : null}
              </output>
            ) : null}
          </p>
        </div>
      ) : null}
    </div>
  );
}
