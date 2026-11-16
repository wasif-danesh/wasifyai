// Record a meeting (ADR-0108, MT2): the microphone is recorded as "You" and the computer's sound (the
// call) as "Others", in one file with two channels. The window's shell records (the screen knows no
// sound device); this screen starts it, shows the time and how loud each side is, stops it, and hands
// the file to the engine to be made into a meeting. Stop is also in the menu bar while it records.
import type { MeetingsApi, MeetingsStatus, WaitingRecording } from "@wasifyai/client";
import { Circle, Mic, Monitor, Square, Trash2, Users } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ConfirmDialog } from "../components/dialog";
import { Notice } from "../components/notice";
import { PageHero } from "../components/page-hero";
import { Spinner } from "../components/spinner";
import { actions, hint, page, panel } from "../styles";
import { DETECT, LanguageField } from "../voice/LanguageField";
import { clock } from "./Meetings";

/** What the shell says about the recording (src-tauri/src/recorder.rs `RecordState`). */
export type RecordState = {
  /** the computer's sound can be recorded on this computer (a Mac, Windows) */
  others_supported: boolean;
  recording: boolean;
  name: string | null;
  seconds: number;
  /** how loud the microphone and the computer's sound are now, 0 to 1 (RMS) */
  levels: [number, number];
  mic: boolean;
  others: boolean;
  /** what is wrong, in words (the microphone not allowed, the computer's sound not allowed) */
  problems: string[];
};

/** A finished recording (`Recorded`): its name in the recordings folder, for the engine. */
export type RecordedMeeting = {
  name: string;
  seconds: number;
  others: boolean;
  problems: string[];
};

/** The shell's recorder, as the window reaches it. */
export type MeetingRecorder = {
  state(): Promise<RecordState>;
  start(): Promise<RecordState>;
  stop(): Promise<RecordedMeeting>;
  /** a recording stopped from the menu bar; one stopped before the screen opened is told at once */
  onRecorded(told: (r: RecordedMeeting) => void): () => void;
  /** stopping from the menu bar went wrong, in words */
  onFailed(told: (problem: string) => void): () => void;
};

export type RecordMeetingProps = {
  api: MeetingsApi;
  recorder: MeetingRecorder;
  /** open a meeting once it is being made */
  onOpen: (id: string) => void;
  /** open Models (the speaker model, the speech-to-text models) */
  onGetModel?: (id?: string) => void;
};

/** A loudness (RMS, 0 to 1) as the share of a meter: -60 dB is empty, 0 dB full. */
export function meter(rms: number): number {
  if (!(rms > 0)) return 0;
  return Math.min(1, Math.max(0, (20 * Math.log10(rms) + 60) / 60));
}

function Level({
  label,
  icon,
  value,
  off,
}: { label: string; icon: React.ReactNode; value: number; off?: string }) {
  const share = meter(value);
  return (
    <div className="grid gap-1.5">
      <span className="flex items-center gap-2 font-semibold">
        {icon}
        {label}
        {off ? <span className={cn(hint, "font-normal")}>{off}</span> : null}
      </span>
      <div
        role="meter"
        aria-label={`${label}: how loud`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(share * 100)}
        className="h-3 overflow-hidden rounded-full bg-muted"
      >
        <i
          className={cn(
            "block h-full rounded-[inherit] transition-[width] duration-150",
            off ? "bg-muted-foreground/40" : "bg-ok",
          )}
          style={{ width: `${share * 100}%` }}
        />
      </div>
    </div>
  );
}

function ago(modified: number): string {
  const d = new Date(modified * 1000);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * The Record screen: Start, then the time, a meter for You and for Others, any problem in words, and
 * Stop; the meeting is then made and opened. Recordings that were not made into a meeting (the window
 * was closed, the speaker model was missing) wait below, to be made into one or thrown away.
 */
export function RecordMeeting({ api, recorder, onOpen, onGetModel }: RecordMeetingProps) {
  const [rec, setRec] = useState<RecordState | null>(null);
  const [status, setStatus] = useState<MeetingsStatus | null>(null);
  const [busy, setBusy] = useState<"starting" | "stopping" | "making" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [language, setLanguage] = useState(DETECT);
  const [discarding, setDiscarding] = useState<WaitingRecording | null>(null);
  // the language at the moment Stop is pressed (the menu bar's Stop reads it too)
  const chosen = useRef(language);
  chosen.current = language;

  const load = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([api.status(), recorder.state()]);
      setStatus(s);
      setRec(r);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Recording could not be opened.");
    }
  }, [api, recorder]);

  useEffect(() => {
    void load();
  }, [load]);

  // the time and the meters, while it records
  const recording = rec?.recording ?? false;
  useEffect(() => {
    if (!recording) return;
    const t = setInterval(() => {
      recorder.state().then(setRec, () => {});
    }, 250);
    return () => clearInterval(t);
  }, [recording, recorder]);

  const make = useCallback(
    async (name: string) => {
      setBusy("making");
      setProblem(null);
      try {
        const lang = chosen.current;
        const made = await api.fromRecording(
          name,
          lang === DETECT ? undefined : { language: lang },
        );
        onOpen(made.id);
      } catch (e) {
        // the recording stays and waits below
        setProblem(e instanceof Error ? e.message : "The meeting could not be made.");
        await load();
      } finally {
        setBusy(null);
      }
    },
    [api, load, onOpen],
  );

  // Stop in the menu bar
  useEffect(() => {
    const offDone = recorder.onRecorded((r) => void make(r.name));
    const offFailed = recorder.onFailed((p) => {
      setProblem(p);
      void load();
    });
    return () => {
      offDone();
      offFailed();
    };
  }, [recorder, make, load]);

  async function start() {
    setProblem(null);
    setBusy("starting");
    try {
      setRec(await recorder.start());
    } catch (e) {
      setProblem(
        typeof e === "string" ? e : e instanceof Error ? e.message : "Recording could not start.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function stop() {
    setBusy("stopping");
    try {
      const done = await recorder.stop();
      setRec((r) => (r ? { ...r, recording: false, levels: [0, 0] } : r));
      await make(done.name);
    } catch (e) {
      setProblem(
        typeof e === "string" ? e : e instanceof Error ? e.message : "Recording could not stop.",
      );
      setBusy(null);
      await load();
    }
  }

  async function discard(r: WaitingRecording) {
    setDiscarding(null);
    try {
      await api.discardRecording(r.name);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "It could not be thrown away.");
    }
    await load();
  }

  const missingModel = status && !status.speaker_model;
  const missingSpeech = status?.speaker_model && !status.speech;
  const canMake = !!status && status.speaker_model && status.speech;
  const waiting = status?.recordings ?? [];

  return (
    <div className={page}>
      <PageHero eyebrow="Meetings" title="Record">
        Your microphone is recorded as You, and the computer's sound, the people on the call, as
        Others. Stop is here and in the menu bar while it records.
      </PageHero>

      {missingModel ? (
        <Notice
          tone="info"
          title="Get the speaker model to make the meeting"
          actions={
            onGetModel ? (
              <Button onClick={() => onGetModel(status.speaker_model_id)}>Open Models</Button>
            ) : null
          }
        >
          You can record now; the recording waits here until the speaker model is on this computer
          (about 490 MB).
        </Notice>
      ) : null}
      {missingSpeech ? (
        <Notice
          tone="info"
          title="Choose a speech-to-text model"
          actions={onGetModel ? <Button onClick={() => onGetModel()}>Open Models</Button> : null}
        >
          {status.speech_problem ??
            "The words are written down by the speech-to-text model you choose."}
        </Notice>
      ) : null}
      {rec && !rec.others_supported ? (
        <Notice tone="warn" title="Only your microphone">
          This computer cannot record its own sound yet, so the people on the call are heard only
          through your microphone. Wear no headphones, or record on a Mac or Windows.
        </Notice>
      ) : null}
      {problem ? (
        <Notice tone="error" title="That did not work" alert>
          {problem}
        </Notice>
      ) : null}

      {rec === null ? (
        <Spinner />
      ) : (
        <section className={cn(panel, "max-w-xl gap-4")} aria-label="Recording">
          {recording ? (
            <>
              <p
                className="m-0 flex items-center gap-2 text-step-2 font-semibold tabular-nums"
                aria-live="off"
              >
                <Circle
                  className="size-4 animate-pulse fill-destructive text-destructive"
                  aria-hidden
                />
                <span>Recording</span>
                <span>{clock(rec.seconds)}</span>
              </p>
              <Level
                label="You"
                icon={<Mic className="size-4" aria-hidden />}
                value={rec.levels[0]}
                off={rec.mic ? undefined : "not heard"}
              />
              <Level
                label="Others"
                icon={<Monitor className="size-4" aria-hidden />}
                value={rec.levels[1]}
                off={
                  rec.others
                    ? undefined
                    : rec.others_supported
                      ? "not allowed"
                      : "not on this computer"
                }
              />
              {rec.problems.length ? (
                <ul className="m-0 grid gap-1 ps-5 text-step--1 text-warn" aria-label="Problems">
                  {rec.problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              ) : null}
              <div className={actions}>
                <Button variant="destructive" onClick={() => void stop()} disabled={busy !== null}>
                  {busy === "stopping" ? <Spinner /> : <Square />}
                  Stop
                </Button>
                <span className={hint}>The meeting is made when you stop.</span>
              </div>
            </>
          ) : (
            <>
              {status?.speech ? (
                <div className="grid gap-2">
                  <LanguageField
                    label="Language of the meeting"
                    ready="Ready to write down"
                    detect
                    models={(status.speech_models ?? []).map((m) => ({
                      ...m,
                      state: "ready" as const,
                    }))}
                    value={language}
                    onChange={setLanguage}
                    disabled={busy !== null}
                  />
                </div>
              ) : null}
              <div className={actions}>
                <Button onClick={() => void start()} disabled={busy !== null}>
                  {busy === "starting" ? <Spinner /> : <Mic />}
                  Start recording
                </Button>
                {busy === "making" ? (
                  <span className={cn(hint, "flex items-center gap-2")}>
                    <Spinner /> Making the meeting…
                  </span>
                ) : (
                  <span className={hint}>
                    The first time, your computer asks to allow the microphone and its own sound.
                  </span>
                )}
              </div>
            </>
          )}
        </section>
      )}

      {waiting.length ? (
        <section className="grid gap-3" aria-label="Recordings waiting">
          <h2 className="m-0 text-ui-lg font-semibold">Recordings not made into a meeting</h2>
          <ul className="m-0 grid list-none gap-3 p-0">
            {waiting.map((r) => (
              <li
                key={r.name}
                className={cn(panel, "flex flex-wrap items-center justify-between gap-3")}
              >
                <span className="grid">
                  <span className="font-semibold">{clock(r.seconds)}</span>
                  <span className={hint}>{ago(r.modified)}</span>
                </span>
                <span className={actions}>
                  <Button
                    onClick={() => void make(r.name)}
                    disabled={!canMake || busy !== null || recording || status?.busy}
                  >
                    <Users />
                    Make it into a meeting
                  </Button>
                  <Button variant="ghost" onClick={() => setDiscarding(r)} disabled={busy !== null}>
                    <Trash2 />
                    Throw away
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {discarding ? (
        <ConfirmDialog
          title="Throw this recording away?"
          message={`The recording of ${clock(discarding.seconds)} is deleted from this computer.`}
          confirmLabel="Throw away"
          onCancel={() => setDiscarding(null)}
          onConfirm={() => void discard(discarding)}
        />
      ) : null}
    </div>
  );
}
