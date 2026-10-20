"use client";
// The options of the chat box (ADR-0083): one bar, token-styled, shared by the current composer and the assistant-ui one. A button is
// there only when it can work (a model that cannot think has no Thinking button), and every disabled button says why. Attach, Search and
// Mic plug into the same bar in the next stages.
import { Brain, Globe, type LucideIcon, Mic, Square } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { type AttachControl, useAttachments } from "./attachments/use-attachments";
import { type MicControl, useDictation } from "./dictation/use-dictation";
import type { ReadAloudControl } from "./read-aloud/use-read-aloud";

export type ComposerOption = {
  id: string;
  label: string;
  Icon: LucideIcon;
  /** a switch that is on (the button looks pressed) */
  pressed?: boolean;
  disabled?: boolean;
  /** what the button does, and why it is disabled when it is */
  hint: string;
  onPress: () => void;
};

export function ComposerOptions({ options }: { options: ComposerOption[] }) {
  if (!options.length) return null;
  return (
    <fieldset
      aria-label="Options for this message"
      className="m-0 flex min-w-0 flex-wrap items-center gap-2 border-0 p-0"
    >
      {options.map(({ id, label, Icon, pressed, disabled, hint, onPress }) => (
        <button
          key={id}
          type="button"
          aria-pressed={pressed === undefined ? undefined : pressed}
          disabled={disabled}
          title={hint}
          aria-label={`${label}. ${hint}`}
          onClick={onPress}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors [@media(pointer:coarse)]:h-11",
            "outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
            pressed
              ? "border-primary bg-accent text-accent-foreground"
              : "text-muted-foreground hover:bg-accent",
          )}
        >
          <Icon className="size-4" aria-hidden="true" />
          <span>{label}</span>
        </button>
      ))}
    </fieldset>
  );
}

/** Web search as the box needs it (ADR-0083): what pressing Search must ask first. */
export type SearchControl = {
  available: boolean;
  /** the person allowed searching with the service named below */
  consented: boolean;
  /** allowed, and the service has its key */
  ready: boolean;
  providerTitle: string;
  /** "Searching the web sends your question to ...": the sentence the person agrees to */
  consentText: string;
  /** the chosen service needs a key that is not saved yet */
  needsKey: boolean;
  /** the person pressed Allow */
  onAllow: () => Promise<void>;
  /** a way to Settings, where the service and its key are chosen */
  onOpenSettings?: () => void;
};

/** Which options a screen can offer (what the engine and the chosen model can do), told by the app. */
export type ComposerOptionsAvailable = {
  thinking?: boolean;
  search?: SearchControl;
  /** dictation: absent where this engine cannot write words down (the button is not shown) */
  mic?: MicControl;
  /** attaching files: absent where this engine cannot keep them (the button is not shown) */
  attach?: AttachControl;
  /** reading a reply aloud: absent where this engine has no voice to offer (no button under a reply). Not a button of the box, but it
   * comes from the same engine facts and reaches both chat screens the same way. */
  readAloud?: ReadAloudControl;
};

/** The card that asks before a search is first allowed, or says what is missing. Plain words, no jargon. */
function SearchNotice({
  heading,
  text,
  error,
  primary,
  onClose,
}: {
  heading: string;
  text: string;
  error: string | null;
  primary?: { label: string; onPress: () => void };
  onClose: () => void;
}) {
  return (
    <section
      aria-label={heading}
      className="mb-2 grid gap-2 rounded-2xl border bg-accent/40 p-3 text-sm"
    >
      <p className="font-medium">{heading}</p>
      <p className="text-muted-foreground">{text}</p>
      {error ? <p className="text-destructive">{error}</p> : null}
      <div className="flex flex-wrap gap-2">
        {primary ? (
          <Button type="button" size="sm" onClick={primary.onPress}>
            {primary.label}
          </Button>
        ) : null}
        <Button type="button" size="sm" variant="outline" onClick={onClose}>
          {primary ? "Not now" : "Close"}
        </Button>
      </div>
    </section>
  );
}

const KEY = "wasifyai.composer.options";
const KEEP = 200;

type Saved = { thinking?: boolean; search?: boolean };

function readAll(): Record<string, Saved> {
  try {
    const raw = localStorage.getItem(KEY);
    const v = raw ? JSON.parse(raw) : {};
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
}

function write(key: string, value: Saved): void {
  try {
    const all = readAll();
    delete all[key]; // newest last, so the oldest can be dropped
    all[key] = value;
    const keys = Object.keys(all);
    for (const k of keys.slice(0, Math.max(0, keys.length - KEEP))) delete all[k];
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    // forgotten: the options are a convenience
  }
}

/**
 * The state of the options, per conversation and remembered in this browser or window (a convenience: if storage is blocked they
 * simply start off). Everything is off by default (Thinking: ADR-0078). A new chat has no id until its first answer; the choice made
 * before it carries over to the id it gets.
 */
export function useComposerOptions(
  conversationId: string | null | undefined,
  available: ComposerOptionsAvailable = {},
  /** where words from the microphone go: into the message box, to be changed and sent by the person (never sent by themselves) */
  onDictation?: (text: string) => void,
) {
  const key = conversationId || "new";
  const [saved, setSaved] = useState<Saved>({});
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  useEffect(() => {
    if (loadedFor === key) return;
    const stored = readAll()[key];
    if (stored) setSaved(stored);
    else if (loadedFor === "new" && key !== "new")
      write(key, saved); // the new chat got its id: keep what was chosen
    else setSaved({});
    setLoadedFor(key);
  }, [key, loadedFor, saved]);

  const setThinking = useCallback(
    (on: boolean) => {
      const next = { ...saved, thinking: on };
      setSaved(next);
      write(key, next);
    },
    [key, saved],
  );
  const setSearch = useCallback(
    (on: boolean) => {
      const next = { ...saved, search: on };
      setSaved(next);
      write(key, next);
    },
    [key, saved],
  );

  const control = available.search?.available ? available.search : undefined;
  const [asking, setAsking] = useState<"consent" | "key" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const thinking = Boolean(available.thinking && saved.thinking);
  const searching = Boolean(control?.ready && saved.search);

  const attach = useAttachments(available.attach);
  const attachOption = attach.option;
  const dictation = useDictation(available.mic, onDictation);
  const { phase: micPhase, toggle: toggleMic } = dictation;
  const hasMic = Boolean(available.mic);

  const bar = useMemo<ComposerOption[]>(() => {
    const out: ComposerOption[] = [];
    if (attachOption) out.push(attachOption);
    if (available.thinking)
      out.push({
        id: "thinking",
        label: "Thinking",
        Icon: Brain,
        pressed: thinking,
        hint: thinking
          ? "On: the assistant thinks first and shows its thinking, which takes longer. Press to turn off."
          : "Off. Press to let the assistant think before it answers, which takes longer.",
        onPress: () => setThinking(!thinking),
      });
    if (control)
      out.push({
        id: "search",
        label: "Search",
        Icon: Globe,
        pressed: searching,
        hint: searching
          ? `On: the assistant may search the web with ${control.providerTitle}. Press to turn off.`
          : !control.consented
            ? `Off. Press to allow searching the web with ${control.providerTitle}.`
            : control.needsKey
              ? `Add your ${control.providerTitle} key to search with it.`
              : `Off. Press to let the assistant search the web with ${control.providerTitle}.`,
        onPress: () => {
          setProblem(null);
          if (!control.consented) setAsking("consent");
          else if (!control.ready) setAsking("key");
          else setSearch(!searching);
        },
      });
    if (hasMic) {
      const recording = micPhase === "recording";
      out.push({
        id: "mic",
        label: recording ? "Stop" : "Mic",
        Icon: recording ? Square : Mic,
        pressed: recording,
        disabled: micPhase === "starting" || micPhase === "transcribing",
        hint: recording
          ? "Listening. Press to stop and write down what you said."
          : micPhase === "transcribing"
            ? "Writing down what you said."
            : "Press, speak, then press again. What you say is written in the box for you to change.",
        onPress: toggleMic,
      });
    }
    return out;
  }, [
    attachOption,
    available.thinking,
    thinking,
    setThinking,
    control,
    searching,
    setSearch,
    hasMic,
    micPhase,
    toggleMic,
  ]);

  const searchNotice: ReactNode =
    control && asking === "consent" ? (
      <SearchNotice
        heading="Allow the assistant to search the web?"
        text={control.consentText}
        error={problem}
        primary={{
          label: "Allow search",
          onPress: () => {
            control
              .onAllow()
              .then(() => {
                setAsking(null);
                setSearch(true);
              })
              .catch((e: unknown) =>
                setProblem(
                  e instanceof Error && e.message ? e.message : "That could not be saved.",
                ),
              );
          },
        }}
        onClose={() => setAsking(null)}
      />
    ) : control && asking === "key" ? (
      <SearchNotice
        heading={`Search needs your ${control.providerTitle} key`}
        text="Add it in Settings, or choose DuckDuckGo there, which needs no key."
        error={null}
        primary={
          control.onOpenSettings
            ? { label: "Open Settings", onPress: () => control.onOpenSettings?.() }
            : undefined
        }
        onClose={() => setAsking(null)}
      />
    ) : null;
  const notice: ReactNode =
    searchNotice || dictation.notice ? (
      <>
        {searchNotice}
        {dictation.notice}
      </>
    ) : null;

  /** what to add to the next message's run input */
  const attachInput = attach.runInput;
  const runInput = useMemo<Record<string, unknown>>(
    () => ({
      ...(thinking ? { thinking: true } : {}),
      ...(searching ? { search: true } : {}),
      ...attachInput,
    }),
    [thinking, searching, attachInput],
  );
  return { bar, thinking, searching, notice, runInput, attach };
}
