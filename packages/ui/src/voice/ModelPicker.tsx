"use client";

import type { VoiceModelInfo, VoiceTask } from "@wasifyai/client";
import { cn } from "../cn";
import { Label } from "../components/label";
import { ModelSelect, groupOfTask, useChoicesFor } from "../models";
import { formatBytes } from "../notebook/format";
import { PageHeader } from "../window-bar";
import { COMMERCIAL_TEXT, costLine, modelOption, stateText } from "./format";

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
  inBody,
}: {
  models: VoiceModelInfo[];
  task: VoiceTask;
  value: string | null;
  onChange: (id: string) => void;
  /** open the Models panel (a missing model is fetched there, after the person sees its size) */
  onGetModel?: (id: string) => void;
  disabled?: boolean;
  /** a second picker on a screen that already has its one in the top bar (editing a track on the music screen) */
  inBody?: boolean;
}) {
  // in the app window the same button and panel as every other group (ADR-0086); on the web, the plain list
  const choices = useChoicesFor(groupOfTask(task), task);
  const chosen = models.find((m) => m.id === value) ?? null;
  if (choices) {
    if (inBody) {
      return (
        <div className="grid justify-items-start gap-2">
          <Label htmlFor={`model-${task}`}>Model</Label>
          <ModelSelect
            group={groupOfTask(task)}
            api={choices}
            value={value}
            disabled={disabled}
            onChanged={(id) => id && onChange(id)}
          />
        </div>
      );
    }
    // at the top of the screen, in the window's bar, like the chat and image screens
    return (
      <PageHeader className="flex h-14 shrink-0 items-center gap-4 border-b px-6 pt-1">
        <div className="flex items-center gap-2 ps-2 text-sm">
          <ModelSelect
            group={groupOfTask(task)}
            api={choices}
            value={value}
            disabled={disabled}
            onChanged={(id) => id && onChange(id)}
          />
        </div>
      </PageHeader>
    );
  }
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
          {chosen.engine === "remote" ? (
            <p>Hosted: what you give this model is sent to its provider to be processed.</p>
          ) : null}
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
                {stateText(chosen)}
                {chosen.state === "can_install" ? ` (${formatBytes(chosen.bytes_missing)})` : ""}.
                {onGetModel && chosen.state === "can_install" ? (
                  <>
                    {" "}
                    <button
                      type="button"
                      className="underline underline-offset-4"
                      onClick={() => onGetModel(chosen.id)}
                    >
                      Get it in the Model hub
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

/** What a screen says under its main button while the chosen model is not on the computer. */
export function NotReadyText({ task, seeAbove }: { task: string; seeAbove?: boolean }) {
  const choices = useChoicesFor(groupOfTask(task), task);
  if (choices) return "Download the model first: use the model button at the top.";
  return seeAbove ? "Set this model up first (see above)." : "Set this model up first.";
}
