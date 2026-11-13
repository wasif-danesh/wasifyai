"use client";

import type { VoiceModelInfo, VoiceTask } from "@wasifyai/client";
import { useId } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Select } from "../components/select";
import { groupOfTask, useChoicesFor } from "../models";
import { LANGUAGES, baseCode, languageLabel, languageName, languagesOf, speaks } from "./languages";

/** Where the language last used on a voice screen is kept (one for every screen). */
export const LANGUAGE_KEY = "wasifyai.voice.language";
export const FIRST_LANGUAGE = "en";
/** "Find it by itself": the model works out the language of a recording */
export const DETECT = "auto";
/** Languages a model must be told: finding them by itself mistakes one for the other (ADR-0043,
 *  docs/spikes/voice-languages-l0.md) */
export const TELL_THE_MODEL = ["bn", "hi"];

/** The models of a list that speak `language`, in the list's order. */
export function modelsFor(models: VoiceModelInfo[], language: string): VoiceModelInfo[] {
  return models.filter((m) => speaks(m.languages, language));
}

/** A language a model speaks, to switch to when the person picks a model that does not speak the
 *  chosen one: English when it can, else its first. */
export function languageForModel(model: VoiceModelInfo, current: string): string {
  if (speaks(model.languages, current)) return baseCode(current);
  const known = languagesOf([model]);
  return known.includes(FIRST_LANGUAGE) ? FIRST_LANGUAGE : (known[0] ?? baseCode(current));
}

/**
 * The language a voice screen starts from (voice languages plan, stage L2). The languages a ready model
 * here speaks come first; every other language the app can name follows, so a person can still choose
 * Bengali when nothing speaks it yet and be told what to get.
 */
export function LanguageField({
  models,
  value,
  onChange,
  disabled,
  ready = "Ready to speak",
  detect = false,
  label = "Language",
}: {
  models: VoiceModelInfo[];
  value: string;
  onChange: (code: string) => void;
  disabled?: boolean;
  /** the heading of the languages a ready model knows */
  ready?: string;
  /** offer "Find it by itself" first (transcription) */
  detect?: boolean;
  /** what the field is called */
  label?: string;
}) {
  const id = useId();
  const spoken = languagesOf(models.filter((m) => m.state === "ready"));
  const rest = LANGUAGES.map((l) => l.code)
    .filter((c) => !spoken.includes(c))
    .sort((a, b) => languageName(a).localeCompare(languageName(b)));
  const option = (c: string) => ({ value: c, label: languageLabel(c) });
  return (
    <div className="grid gap-2">
      <Label htmlFor={id} className="font-semibold text-ui-lg">
        {label}
      </Label>
      <Select
        id={id}
        value={value === DETECT ? DETECT : baseCode(value)}
        disabled={disabled}
        options={[
          ...(detect
            ? [{ label: "", options: [{ value: DETECT, label: "Find it by itself" }] }]
            : []),
          ...(spoken.length ? [{ label: ready, options: spoken.map(option) }] : []),
          ...(rest.length ? [{ label: "Other languages", options: rest.map(option) }] : []),
        ]}
        onValueChange={onChange}
      />
    </div>
  );
}

/**
 * What a voice screen says when no model it can use now speaks the chosen language: the models that
 * would, to get (on this computer) or to use (in the cloud). In the window the model list can be opened
 * from here too, since a cloud model is chosen there (its Cloud tab).
 */
export function NoModelSpeaks({
  language,
  verb = "speaks",
  task,
  models,
  onUse,
  onGetModel,
  onOpenModels,
}: {
  language: string;
  /** what a model does with the language: "speaks", "writes down" */
  verb?: string;
  task: VoiceTask;
  /** the models that speak the language, none of them ready */
  models: VoiceModelInfo[];
  onUse: (id: string) => void;
  onGetModel?: (id: string) => void;
  /** open the window's model list */
  onOpenModels?: () => void;
}) {
  const choices = useChoicesFor(groupOfTask(task), task);
  const name = languageName(language);
  const local = onGetModel ? models.filter((m) => m.engine !== "remote") : [];
  const cloud = models.filter((m) => m.engine === "remote");
  const openList = choices && onOpenModels ? onOpenModels : null;
  return (
    <div role="alert" className="grid gap-2 rounded-md border border-dashed p-3 text-sm">
      <p className="m-0">
        No model here {verb} {name} yet.
      </p>
      {local.length || cloud.length || openList ? (
        <div className="flex flex-wrap gap-2">
          {local.map((m) => (
            <Button
              key={m.id}
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                onUse(m.id);
                onGetModel?.(m.id);
              }}
            >
              Get {m.title}
            </Button>
          ))}
          {cloud.map((m) => (
            <Button
              key={m.id}
              type="button"
              size="sm"
              variant="outline"
              onClick={() => onUse(m.id)}
            >
              Use {m.title} (cloud)
            </Button>
          ))}
          {openList ? (
            <Button type="button" size="sm" variant="outline" onClick={openList}>
              Choose a model, here or in the cloud
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
