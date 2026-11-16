"use client";

import type { Meeting, MeetingSummary, MeetingsApi, MeetingsStatus } from "@wasifyai/client";
import {
  ArrowLeft,
  Check,
  FileText,
  Pencil,
  Square,
  Trash2,
  Upload,
  UserRound,
  Users,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ConfirmDialog, NameDialog } from "../components/dialog";
import { EmptyState } from "../components/empty-state";
import { Notice } from "../components/notice";
import { PageHero } from "../components/page-hero";
import { Bar } from "../components/progress-bar";
import { Spinner } from "../components/spinner";
import { fileNameFor, savedText, useSaveCopy } from "../save";
import { actions, backLink, hint, page, panel } from "../styles";
import { DETECT, LanguageField, TELL_THE_MODEL } from "../voice/LanguageField";
import { languageName, speaks } from "../voice/languages";
import { Asking } from "./Asking";
import { Reports } from "./Reports";

export const MEETING_ACCEPT =
  "audio/*,video/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.webm,.mp4,.mov,.mkv,.wma,.aiff,.aif,.caf";

// a colour per speaker, from the design tokens, so the same speaker reads the same everywhere
const TONES = [
  "text-primary border-primary/40 bg-primary/5",
  "text-warn border-warn/40 bg-warn/5",
  "text-ok border-ok/40 bg-ok/5",
  "text-brand-2 border-brand-2/40 bg-brand-2/5",
];

function tone(key: string): string {
  const n = Number.parseInt(key.slice(1), 10);
  return TONES[(Number.isFinite(n) ? n - 1 : 0) % TONES.length] ?? TONES[0] ?? "";
}

/** 75 -> "1:15", 3725 -> "1:02:05" */
/** Let go of a recording's address: an object URL holds the whole file; a link holds nothing. */
function drop(url: string): void {
  if (url.startsWith("blob:")) URL.revokeObjectURL(url);
}

export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

function length(seconds: number | null): string {
  if (!seconds) return "";
  const m = Math.round(seconds / 60);
  return m < 1 ? "under a minute" : m === 1 ? "1 minute" : `${m} minutes`;
}

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export type MeetingsProps = {
  api: MeetingsApi;
  /** Open Models at a model (the speaker model, or the speech-to-text models). */
  onGetModel?: (id?: string) => void;
  /** Open a meeting at once (from a link or search). */
  initialId?: string | null;
  /** Open a notebook the meeting is in (MT5). */
  onOpenNotebook?: (id: string) => void;
  /** Where Models are this person's to get (the desktop); on the web an admin chooses them. */
  hosted?: boolean;
};

/**
 * Meetings (ADR-0108, MT1): the list of meetings and "New meeting from a file"; a meeting's page shows
 * who said what, lets the person name each speaker, play the recording from a line, save the transcript
 * as text and delete the meeting; a speaker may be suggested as one of People (MT3), and reports are written
 * from templates (MT4); questions are answered through notebooks, and a meeting can be added to one (MT5).
 */
export function Meetings({ api, onGetModel, initialId, onOpenNotebook, hosted }: MeetingsProps) {
  const [status, setStatus] = useState<MeetingsStatus | null>(null);
  const [items, setItems] = useState<MeetingSummary[] | null>(null);
  const [openId, setOpenId] = useState<string | null>(initialId ?? null);
  const [problem, setProblem] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  // what the meeting is in: "Find it by itself" leaves it to the model, which mixes up Bengali and Hindi
  const [language, setLanguage] = useState(DETECT);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [s, list] = await Promise.all([api.status(), api.list()]);
      setStatus(s);
      setItems(list);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Meetings could not be opened.");
      setItems((i) => i ?? []);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const working = items?.some((m) => m.status === "working") ?? false;
  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => void load(), 1500);
    return () => clearInterval(t);
  }, [working, load]);

  async function send(file: File) {
    setProblem(null);
    setSending(true);
    try {
      const made = await api.fromFile(file, language === DETECT ? undefined : { language });
      await load();
      setOpenId(made.id);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That recording could not be used.");
    } finally {
      setSending(false);
      if (input.current) input.current.value = "";
    }
  }

  if (openId)
    return (
      <MeetingPage
        api={api}
        id={openId}
        onGetModel={onGetModel}
        onOpenNotebook={onOpenNotebook}
        hosted={hosted}
        onBack={() => {
          setOpenId(null);
          void load();
        }}
      />
    );

  const missingModel = status && !status.speaker_model;
  const missingSpeech = status?.speaker_model && !status.speech;
  const canMake = !!status && status.speaker_model && status.speech && !status.busy;
  // the model that will write it down: the chosen one when it knows the language, else a ready one
  // that does (the engine picks the same way)
  const ready = status?.speech_models ?? [];
  const writer =
    language === DETECT || !status?.speech_model
      ? status?.speech_model
      : (ready.find((m) => m.id === status.speech_model?.id && speaks(m.languages, language)) ??
        ready.find((m) => speaks(m.languages, language)) ??
        null);

  return (
    <div className={page}>
      <PageHero eyebrow="Meetings" title="View meetings">
        A recording becomes a meeting: who spoke when, and what they said.{" "}
        {hosted
          ? "The transcription service tells the speakers apart."
          : "The speakers are told apart on this computer."}
      </PageHero>

      {missingModel ? (
        <Notice
          tone="info"
          title="Get the speaker model first"
          actions={
            onGetModel ? (
              <Button onClick={() => onGetModel(status.speaker_model_id)}>Open Models</Button>
            ) : null
          }
        >
          It tells up to four people of a recording apart (about 490 MB, shown before it starts).
        </Notice>
      ) : null}
      {missingSpeech ? (
        <Notice
          tone="info"
          title={hosted ? "Meetings are not set up yet" : "Choose a speech-to-text model"}
          actions={onGetModel ? <Button onClick={() => onGetModel()}>Open Models</Button> : null}
        >
          {status.speech_problem ??
            "The words are written down by the speech-to-text model you choose."}
        </Notice>
      ) : null}
      {problem ? (
        <Notice tone="error" title="That did not work" alert>
          {problem}
        </Notice>
      ) : null}

      {status?.speech ? (
        <div className="grid max-w-sm gap-2">
          <LanguageField
            label="Language of the meeting"
            ready="Ready to write down"
            detect
            models={ready.map((m) => ({ ...m, state: "ready" as const }))}
            value={language}
            onChange={setLanguage}
            disabled={sending}
          />
          {language === DETECT ? (
            <p className={cn(hint, "m-0")}>
              In {TELL_THE_MODEL.map(languageName).join(" or ")}? Choose it: a model finding the
              language by itself mixes them up.
            </p>
          ) : writer === null ? (
            <p className={cn(hint, "m-0")}>
              No speech-to-text model {hosted ? "here" : "on this computer"} knows{" "}
              {languageName(language)} yet.
              {onGetModel ? (
                <>
                  {" "}
                  <button
                    type="button"
                    className="text-primary underline"
                    onClick={() => onGetModel()}
                  >
                    Get one in Models
                  </button>
                  .
                </>
              ) : null}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className={actions}>
        <input
          ref={input}
          type="file"
          accept={MEETING_ACCEPT}
          className="sr-only"
          aria-label="Recording of a meeting"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void send(f);
          }}
        />
        <Button
          disabled={!canMake || sending || writer === null}
          onClick={() => input.current?.click()}
        >
          {sending ? <Spinner /> : <Upload />}
          New meeting from a file
        </Button>
        {status?.busy ? <span className={hint}>A meeting is being made.</span> : null}
        {writer ? <span className={hint}>Written down with {writer.title}.</span> : null}
      </div>

      {items === null ? (
        <Spinner />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No meetings yet"
          text="Choose a recording of a meeting: a sound or video file from your computer."
        />
      ) : (
        <ul className="grid gap-3" aria-label="Meetings">
          {items.map((m) => (
            <li key={m.id}>
              <button
                type="button"
                onClick={() => setOpenId(m.id)}
                className={cn(panel, "w-full gap-2 text-start hover:border-primary/40")}
              >
                <span className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-ui-lg font-semibold">{m.title}</span>
                  <span className={hint}>{when(m.created_at)}</span>
                </span>
                {m.status === "working" ? (
                  <span className="grid gap-1.5">
                    <span className={hint}>{m.stage || "Waiting"}</span>
                    <Bar value={m.progress} />
                  </span>
                ) : m.status === "done" ? (
                  <span className={hint}>
                    {length(m.seconds)} · {m.speakers.length} speaker
                    {m.speakers.length === 1 ? "" : "s"}: {m.speakers.map((s) => s.name).join(", ")}
                  </span>
                ) : (
                  <span className="text-step--1 text-destructive">
                    {m.status === "cancelled" ? "Stopped." : m.error || "It could not be made."}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MeetingPage({
  api,
  id,
  onBack,
  onGetModel,
  onOpenNotebook,
  hosted,
}: {
  api: MeetingsApi;
  id: string;
  onBack: () => void;
  onGetModel?: (id?: string) => void;
  onOpenNotebook?: (id: string) => void;
  hosted?: boolean;
}) {
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [known, setKnown] = useState<string[]>([]);
  const [voiceprints, setVoiceprints] = useState<{ ready: boolean; id: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [naming, setNaming] = useState<{ key: string; name: string } | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [audio, setAudio] = useState<string | null>(null);
  const player = useRef<HTMLAudioElement>(null);
  const saveCopy = useSaveCopy();

  const load = useCallback(async () => {
    try {
      setMeeting(await api.get(id));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That meeting could not be opened.");
    }
  }, [api, id]);

  useEffect(() => {
    void load();
  }, [load]);

  // the people already known, offered when a speaker is named; whether voices can be known again
  useEffect(() => {
    api.people().then(
      (all) => setKnown(all.map((p) => p.name)),
      () => setKnown([]),
    );
    api.status().then(
      (s) => setVoiceprints({ ready: s.voiceprint_model, id: s.voiceprint_model_id }),
      () => setVoiceprints(null),
    );
  }, [api]);

  const working = meeting?.status === "working";
  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => void load(), 1500);
    return () => clearInterval(t);
  }, [working, load]);

  const done = meeting?.status === "done";
  useEffect(() => {
    if (!done) return;
    let url: string | null = null;
    let gone = false;
    api
      .audioUrl(id)
      .then((u) => {
        if (gone) drop(u);
        else {
          url = u;
          setAudio(u);
        }
      })
      .catch(() => setAudio(null));
    return () => {
      gone = true;
      if (url) drop(url);
    };
  }, [api, id, done]);

  async function act(work: () => Promise<Meeting | null>, fallback: string) {
    setProblem(null);
    setNote(null);
    try {
      const out = await work();
      if (out) setMeeting(out);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : fallback);
    }
  }

  function playFrom(seconds: number) {
    const el = player.current;
    if (!el) return;
    el.currentTime = seconds;
    void el.play().catch(() => undefined);
  }

  const names = new Map(meeting?.speakers.map((s) => [s.key, s.name]) ?? []);

  return (
    <div className={page}>
      <button type="button" className={backLink} onClick={onBack}>
        <ArrowLeft className="size-4" /> Meetings
      </button>
      {meeting === null ? (
        problem ? (
          <Notice tone="error" title="That did not work" alert>
            {problem}
          </Notice>
        ) : (
          <Spinner />
        )
      ) : (
        <>
          <PageHero eyebrow="Meeting" title={meeting.title}>
            {[when(meeting.created_at), length(meeting.seconds), meeting.source_name]
              .filter(Boolean)
              .join(" · ")}
          </PageHero>

          <div className={actions}>
            <Button variant="outline" size="sm" onClick={() => setRenaming(true)}>
              <Pencil /> Rename
            </Button>
            {done ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  void act(async () => {
                    const out = await saveCopy({
                      name: fileNameFor(meeting.title, "txt", "meeting"),
                      blob: () => api.exportText(meeting.id),
                    });
                    if (out) setNote(savedText(out));
                    return null;
                  }, "That could not be saved.")
                }
              >
                <FileText /> Save as text
              </Button>
            ) : null}
            {working ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => void act(() => api.stop(meeting.id), "It could not be stopped.")}
              >
                <Square /> Stop
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" onClick={() => setDeleting(true)}>
              <Trash2 /> Delete
            </Button>
          </div>

          {note ? <p className={hint}>{note}</p> : null}
          {problem ? (
            <Notice tone="error" title="That did not work" alert>
              {problem}
            </Notice>
          ) : null}

          {working ? (
            <section className={panel} aria-live="polite">
              <p className="font-semibold">{meeting.stage || "Waiting"}</p>
              <Bar value={meeting.progress} />
              <p className={hint}>
                You can leave this screen; the meeting will be in Meetings when it is ready.
              </p>
            </section>
          ) : null}
          {meeting.status === "failed" || meeting.status === "cancelled" ? (
            <Notice
              tone="warn"
              title={meeting.status === "cancelled" ? "Stopped" : "It could not be made"}
            >
              {meeting.error}
            </Notice>
          ) : null}

          {done ? (
            <>
              <section className={panel} aria-label="Speakers">
                <h2 className="text-ui-lg font-semibold">Speakers</h2>
                <ul className="flex flex-wrap gap-2">
                  {meeting.speakers.map((s) => (
                    <li key={s.key} className="flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => setNaming({ key: s.key, name: s.name })}
                        className={cn(
                          "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-semibold",
                          tone(s.key),
                        )}
                        aria-label={`Name ${s.name}`}
                      >
                        {s.person_id ? <UserRound className="size-3.5" aria-hidden /> : null}
                        {s.name}
                        <span className="font-normal text-muted-foreground">
                          {clock(s.seconds)}
                        </span>
                        <Pencil className="size-3.5" />
                      </button>
                      {s.suggestion ? (
                        <span
                          className="inline-flex items-center gap-1 rounded-full border border-dashed px-2.5 py-1 text-sm"
                          aria-label={`Suggestion for ${s.name}`}
                        >
                          <span>
                            {s.suggestion.status === "likely" ? "Is this" : "Could this be"}{" "}
                            <strong>{s.suggestion.name}</strong>?
                          </span>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`Yes, ${s.name} is ${s.suggestion.name}`}
                            onClick={() => {
                              const hint = s.suggestion;
                              if (hint)
                                void act(
                                  () =>
                                    api.nameSpeaker(meeting.id, s.key, hint.name, hint.person_id),
                                  "The name could not be saved.",
                                );
                            }}
                          >
                            <Check />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`No, ${s.name} is not ${s.suggestion.name}`}
                            onClick={() => {
                              const hint = s.suggestion;
                              if (hint)
                                void act(
                                  () => api.notThisPerson(meeting.id, s.key, hint.person_id),
                                  "That could not be saved.",
                                );
                            }}
                          >
                            <X />
                          </Button>
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
                <p className={hint}>
                  {hosted
                    ? "Choose a speaker to give them a name: they join People."
                    : "Choose a speaker to give them a name: they join People, and later meetings suggest them by voice. A suggestion is only named when you say Yes. Up to four people are told apart in one recording."}
                </p>
                {voiceprints && !voiceprints.ready && onGetModel ? (
                  <p className={hint}>
                    To have people suggested by voice, get the voiceprint model (about 26 MB).
                    {onGetModel ? (
                      <>
                        {" "}
                        <button
                          type="button"
                          className="text-primary underline"
                          onClick={() => onGetModel(voiceprints.id)}
                        >
                          Open Models
                        </button>
                        .
                      </>
                    ) : null}
                  </p>
                ) : null}
                {audio ? (
                  // biome-ignore lint/a11y/useMediaCaption: the transcript below is the caption
                  <audio ref={player} src={audio} controls className="w-full" />
                ) : null}
              </section>

              <Reports api={api} meeting={meeting} onChanged={load} />
              <Asking
                api={api}
                meeting={meeting}
                onChanged={load}
                onOpenNotebook={onOpenNotebook}
              />

              <section className="grid gap-4" aria-label="Transcript">
                {meeting.lines.length === 0 ? (
                  <p className={hint}>Nothing was said that could be written down.</p>
                ) : (
                  meeting.lines.map((line, i) => (
                    <div key={`${line.start}-${i}`} className="grid gap-1">
                      <div className="flex items-center gap-2.5">
                        <span
                          className={cn("text-sm font-semibold", tone(line.speaker).split(" ")[0])}
                        >
                          {names.get(line.speaker) ?? line.speaker}
                        </span>
                        <button
                          type="button"
                          className="text-step--1 text-muted-foreground tabular-nums hover:text-foreground"
                          onClick={() => playFrom(line.start)}
                          aria-label={`Play from ${clock(line.start)}`}
                          disabled={!audio}
                        >
                          {clock(line.start)}
                        </button>
                      </div>
                      <p className="leading-relaxed">{line.text}</p>
                    </div>
                  ))
                )}
              </section>
            </>
          ) : null}

          {naming ? (
            <NameDialog
              title="Name this speaker"
              label="Their name"
              initial={naming.name}
              confirmLabel="Save"
              choices={known}
              onCancel={() => setNaming(null)}
              onSubmit={(name) => {
                const key = naming.key;
                setNaming(null);
                void act(async () => {
                  const out = await api.nameSpeaker(meeting.id, key, name);
                  if (!known.some((k) => k.toLowerCase() === name.trim().toLowerCase()))
                    setKnown((all) => [...all, name.trim()]);
                  return out;
                }, "The name could not be saved.");
              }}
            />
          ) : null}
          {renaming ? (
            <NameDialog
              title="Rename the meeting"
              label="Name"
              initial={meeting.title}
              confirmLabel="Rename"
              onCancel={() => setRenaming(false)}
              onSubmit={(title) => {
                setRenaming(false);
                if (title.trim())
                  void act(() => api.rename(meeting.id, title.trim()), "It could not be renamed.");
              }}
            />
          ) : null}
          {deleting ? (
            <ConfirmDialog
              title="Delete this meeting?"
              message="Its recording, transcript, reports and what was learnt of its speakers' voices are deleted. This cannot be undone."
              confirmLabel="Delete"
              destructive
              onCancel={() => setDeleting(false)}
              onConfirm={() => {
                setDeleting(false);
                void act(async () => {
                  await api.remove(meeting.id);
                  onBack();
                  return null;
                }, "It could not be deleted.");
              }}
            />
          ) : null}
        </>
      )}
    </div>
  );
}
