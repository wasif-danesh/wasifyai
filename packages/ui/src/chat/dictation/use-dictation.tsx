"use client";
// Dictation for the chat box (ADR-0083, decision 5): press Mic, speak, press Stop; the words land in the box to be changed, and are
// never sent by themselves. This hook is the state of that and the cards that tell the person what is happening; the Mic button itself
// is one entry in the options bar (composer-options.tsx).
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../../components/button";
import { Bar } from "../../components/progress-bar";
import { formatBytes } from "../../notebook/format";
import { MAX_RECORD_SECONDS, type Recorder, type Recording, micProblem } from "./recorder";

/** Getting dictation ready when there is no speech model yet: what it is, where from, how big, and the one click. */
export type MicSetup = {
  title: string;
  /** the host the model comes from */
  from: string;
  /** everything that would be downloaded, in bytes */
  bytes: number;
  /** does it; reports how far it is (0 to 1, or null while unknown) and resolves when dictation is ready */
  run(onProgress: (fraction: number | null) => void): Promise<void>;
};

/** What the Mic button needs from the app. */
export type MicControl = {
  /** listen to the microphone (the real recorder unless a test gives another) */
  record: Recorder;
  /** write a recorded clip down */
  transcribe(wav: Blob): Promise<{ text: string; displaced?: string | null }>;
  /** present while there is no speech model: pressing Mic then offers this instead of recording */
  setup?: MicSetup;
};

/** Words put after what is in the box already, with one space between. */
export function joinDictation(draft: string, text: string): string {
  const add = text.trim();
  if (!add) return draft;
  if (!draft) return add;
  return /\s$/.test(draft) ? draft + add : `${draft} ${add}`;
}

/** "0:07" */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const QUIET = 0.004; // below this, a clip has nothing in it (the engine checks the same)
const SHORTEST = 0.3;

export type Dictation = {
  phase: "idle" | "starting" | "recording" | "transcribing";
  /** the Mic button was pressed with no speech model: the setup card is open */
  settingUp: boolean;
  /** press: start, stop, or open the setup card */
  toggle: () => void;
  notice: ReactNode;
};

export function Card({
  heading,
  children,
  actions,
  alert,
}: {
  heading?: string;
  children?: ReactNode;
  actions?: ReactNode;
  alert?: boolean;
}) {
  return (
    <section
      aria-label={heading}
      role={alert ? "alert" : undefined}
      className="mb-2 grid gap-2 rounded-2xl border bg-accent/40 p-3 text-sm"
    >
      {children}
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </section>
  );
}

export function useDictation(
  control: MicControl | undefined,
  onText: ((text: string) => void) | undefined,
): Dictation {
  const [phase, setPhase] = useState<Dictation["phase"]>("idle");
  const [label, setLabel] = useState("");
  const [seconds, setSeconds] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [settingUp, setSettingUp] = useState(false);
  const [setup, setSetup] = useState<{ working: boolean; fraction: number | null; done: boolean }>({
    working: false,
    fraction: null,
    done: false,
  });
  const recording = useRef<Recording | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const alive = useRef(true);
  const textTo = useRef(onText);
  textTo.current = onText;
  const controlRef = useRef(control);
  controlRef.current = control;

  const clearTimer = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  }, []);

  // the microphone is released if the screen goes away while it is listening
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      clearTimer();
      recording.current?.cancel();
      recording.current = null;
    };
  }, [clearTimer]);

  const finish = useCallback(async () => {
    const rec = recording.current;
    const c = controlRef.current;
    if (!rec || !c) return;
    recording.current = null;
    clearTimer();
    setPhase("transcribing");
    try {
      const clip = await rec.stop();
      if (clip.seconds < SHORTEST) {
        setProblem("That was too short to write down. Speak for a little longer.");
        return;
      }
      if (clip.peak < QUIET) {
        setProblem(
          "Nothing could be heard. Check that the right microphone is chosen and try again.",
        );
        return;
      }
      const got = await c.transcribe(clip.wav);
      if (!alive.current) return;
      if (got.text.trim()) {
        textTo.current?.(got.text);
        if (got.displaced === "chat")
          setNote(
            "The chat model was put away to make room for dictation. It loads again when you send your next message.",
          );
      } else {
        setProblem("No words were caught. Speak closer to the microphone and try again.");
      }
    } catch (e) {
      if (alive.current)
        setProblem(e instanceof Error && e.message ? e.message : "That could not be written down.");
    } finally {
      if (alive.current) setPhase("idle");
    }
  }, [clearTimer]);

  const toggle = useCallback(() => {
    const c = controlRef.current;
    if (!c) return;
    setProblem(null);
    setNote(null);
    if (phase === "recording") {
      void finish();
      return;
    }
    if (phase !== "idle") return;
    if (c.setup) {
      setSettingUp(true);
      return;
    }
    setPhase("starting");
    c.record()
      .then((rec) => {
        if (!alive.current) {
          rec.cancel();
          return;
        }
        recording.current = rec;
        setLabel(rec.label);
        setSeconds(0);
        setPhase("recording");
        const began = Date.now();
        timer.current = setInterval(() => {
          const s = Math.floor((Date.now() - began) / 1000);
          setSeconds(s);
          if (s >= MAX_RECORD_SECONDS) void finish();
        }, 1000);
      })
      .catch((e: unknown) => {
        if (!alive.current) return;
        setProblem(micProblem(e).message);
        setPhase("idle");
      });
  }, [phase, finish]);

  const cancel = () => {
    recording.current?.cancel();
    recording.current = null;
    clearTimer();
    setPhase("idle");
  };

  const runSetup = (s: NonNullable<MicControl["setup"]>) => {
    setProblem(null);
    setSetup({ working: true, fraction: null, done: false });
    s.run((fraction) => alive.current && setSetup({ working: true, fraction, done: false }))
      .then(() => alive.current && setSetup({ working: false, fraction: 1, done: true }))
      .catch((e: unknown) => {
        if (!alive.current) return;
        setSetup({ working: false, fraction: null, done: false });
        setProblem(e instanceof Error && e.message ? e.message : "That could not be set up.");
      });
  };

  let notice: ReactNode = null;
  if (phase === "recording") {
    notice = (
      <Card heading="Dictation">
        <output className="flex flex-wrap items-center gap-2">
          <span
            aria-hidden="true"
            className="size-2.5 rounded-full bg-destructive motion-safe:animate-pulse"
          />
          <span className="font-medium">
            Listening{label ? ` with ${label}` : ""} · {clock(seconds)}
          </span>
          <span className="text-muted-foreground">Press Stop when you are done.</span>
        </output>
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" onClick={cancel}>
            Cancel
          </Button>
        </div>
      </Card>
    );
  } else if (phase === "transcribing") {
    notice = (
      <Card heading="Dictation">
        <output className="text-muted-foreground">Transcribing…</output>
      </Card>
    );
  } else if (settingUp && control?.setup) {
    const s = control.setup;
    notice = (
      <Card
        heading="Set up dictation"
        actions={
          setup.working ? undefined : (
            <>
              <Button type="button" size="sm" onClick={() => runSetup(s)} disabled={setup.working}>
                Download {formatBytes(s.bytes)}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setSettingUp(false)}>
                Not now
              </Button>
            </>
          )
        }
      >
        <p className="font-medium">Set up dictation</p>
        <p className="text-muted-foreground">
          Dictation writes down what you say with a speech model that runs on this computer, so your
          voice is not sent anywhere and is not kept. It needs {s.title}
          {s.from ? `, from ${s.from}` : ""}: {formatBytes(s.bytes)} to download once.
        </p>
        {setup.working ? (
          <div className="grid gap-1">
            <Bar value={setup.fraction ?? undefined} />
            <output className="text-muted-foreground">Getting dictation ready…</output>
          </div>
        ) : null}
        {problem ? <p className="text-destructive">{problem}</p> : null}
      </Card>
    );
  } else if (setup.done && !control?.setup) {
    notice = (
      <Card
        heading="Dictation"
        actions={
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setSetup({ ...setup, done: false })}
          >
            Close
          </Button>
        }
      >
        <output>Dictation is ready. Press Mic to start.</output>
      </Card>
    );
  } else if (problem) {
    notice = (
      <Card
        heading="Dictation"
        alert
        actions={
          <Button type="button" size="sm" variant="outline" onClick={() => setProblem(null)}>
            Close
          </Button>
        }
      >
        <p className="text-destructive">{problem}</p>
      </Card>
    );
  } else if (note) {
    notice = (
      <Card
        heading="Dictation"
        actions={
          <Button type="button" size="sm" variant="outline" onClick={() => setNote(null)}>
            Close
          </Button>
        }
      >
        <output className="text-muted-foreground">{note}</output>
      </Card>
    );
  }

  return { phase, settingUp, toggle, notice };
}
