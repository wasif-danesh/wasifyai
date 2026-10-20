"use client";
// Read aloud for the chat (ADR-0083, CU3): a button on each assistant reply speaks it with our own speech model on this computer. It is
// opt-in (only a click starts it, never a new reply), local (the text goes to the engine on this computer and the sound comes back), and
// keeps nothing. The engine cuts a reply into passages; this asks for the next one while the first plays, so sound starts after one
// passage and not after the whole reply. The state, the setup card and the button are here; both chat screens use them.
import type { ReadAloudPart } from "@wasifyai/client";
import { Loader2, Square, Volume2 } from "lucide-react";
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { cn } from "../../cn";
import { Button } from "../../components/button";
import { Bar } from "../../components/progress-bar";
import { formatBytes } from "../../notebook/format";
import { Card, type MicSetup } from "../dictation/use-dictation";
import { type Player, createPlayer } from "./player";

/** Getting read aloud ready when there is no speech model yet: the same card as dictation's, and what languages the voice speaks. */
export type ReadAloudSetup = MicSetup & { languages?: string[] };

/** What the Read aloud button needs from the app. */
export type ReadAloudControl = {
  /** one passage of a reply, spoken (the engine turns the text into plain words and cuts it) */
  speak(text: string, part: number, signal: AbortSignal): Promise<ReadAloudPart>;
  /** present while there is no speech model: pressing Read aloud then offers this instead of speaking */
  setup?: ReadAloudSetup;
  /** the real player unless a test gives another */
  player?: () => Player;
};

/** "American English, British English" for the codes a voice lists; the codes themselves where the browser does not know them. */
export function languageNames(codes: string[] | undefined): string {
  if (!codes?.length) return "";
  let names: Intl.DisplayNames | null = null;
  try {
    names = new Intl.DisplayNames([typeof navigator === "undefined" ? "en" : navigator.language], {
      type: "language",
    });
  } catch {
    names = null;
  }
  const out: string[] = [];
  for (const code of codes) {
    let name = code;
    try {
      name = names?.of(code) ?? code;
    } catch {
      // not a code the browser knows: shown as it is
    }
    if (!out.includes(name)) out.push(name);
  }
  return out.join(", ");
}

type Active = { id: string; phase: "loading" | "speaking"; part: number; parts: number };
type Said = { id: string; text: string };

export type ReadAloud = {
  /** there is something to offer: a speech model is ready, or can be got */
  available: boolean;
  active: Active | null;
  toggle: (id: string, text: string) => void;
  stop: () => void;
  /** the message the setup card, a problem or a note belongs to */
  noticeFor: string | null;
  notice: ReactNode;
};

const FAILED = "That could not be read aloud.";

export function useReadAloud(control: ReadAloudControl | undefined): ReadAloud {
  const [active, setActive] = useState<Active | null>(null);
  const [problem, setProblem] = useState<Said | null>(null);
  const [note, setNote] = useState<Said | null>(null);
  const [settingUp, setSettingUp] = useState<string | null>(null);
  const [setup, setSetupState] = useState<{
    working: boolean;
    fraction: number | null;
    done: boolean;
  }>({ working: false, fraction: null, done: false });
  const alive = useRef(true);
  const run = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const player = useRef<Player | null>(null);
  const controlRef = useRef(control);
  controlRef.current = control;

  const halt = useCallback(() => {
    run.current += 1;
    abort.current?.abort();
    abort.current = null;
    player.current?.stop();
  }, []);

  // the sound stops if the screen goes away
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      halt();
    };
  }, [halt]);

  const begin = useCallback(
    async (id: string, text: string) => {
      const c = controlRef.current;
      if (!c) return;
      halt();
      const mine = run.current;
      const ac = new AbortController();
      abort.current = ac;
      player.current ??= (c.player ?? createPlayer)();
      player.current.unlock(); // inside the click: later passages are allowed to play
      setProblem(null);
      setNote(null);
      setActive({ id, phase: "loading", part: 0, parts: 1 });
      try {
        let current = c.speak(text, 0, ac.signal);
        for (let i = 0; ; i++) {
          const got = await current;
          if (run.current !== mine) return;
          if (i === 0) {
            const bits: string[] = [];
            if (got.truncated)
              bits.push("This reply is long, so only the first part is read aloud.");
            if (got.displaced === "chat")
              bits.push(
                "The chat model was put away to make room for the voice. It loads again when you send your next message.",
              );
            if (bits.length) setNote({ id, text: bits.join(" ") });
          }
          // the next passage is asked for now, while this one plays
          const next = i + 1 < got.parts ? c.speak(text, i + 1, ac.signal) : null;
          next?.catch(() => {});
          setActive({ id, phase: "speaking", part: i, parts: got.parts });
          await (player.current as Player).play(got.wav);
          if (run.current !== mine) return;
          if (!next) break;
          setActive({ id, phase: "loading", part: i + 1, parts: got.parts });
          current = next;
        }
      } catch (e) {
        if (run.current === mine && alive.current)
          setProblem({ id, text: e instanceof Error && e.message ? e.message : FAILED });
      } finally {
        if (run.current === mine) {
          abort.current = null;
          if (alive.current) setActive(null);
        }
      }
    },
    [halt],
  );

  const stop = useCallback(() => {
    halt();
    setActive(null);
  }, [halt]);

  const toggle = useCallback(
    (id: string, text: string) => {
      const c = controlRef.current;
      if (!c) return;
      if (active?.id === id) {
        stop();
        return;
      }
      setProblem(null);
      setNote(null);
      if (c.setup) {
        stop();
        setSettingUp(id);
        return;
      }
      void begin(id, text);
    },
    [active, begin, stop],
  );

  const runSetup = (s: ReadAloudSetup) => {
    setProblem(null);
    setSetupState({ working: true, fraction: null, done: false });
    s.run((fraction) => alive.current && setSetupState({ working: true, fraction, done: false }))
      .then(() => alive.current && setSetupState({ working: false, fraction: 1, done: true }))
      .catch((e: unknown) => {
        if (!alive.current) return;
        setSetupState({ working: false, fraction: null, done: false });
        setProblem({
          id: settingUp ?? "",
          text: e instanceof Error && e.message ? e.message : "That could not be set up.",
        });
      });
  };

  let noticeFor: string | null = null;
  let notice: ReactNode = null;
  const close = (fn: () => void) => (
    <Button type="button" size="sm" variant="outline" onClick={fn}>
      Close
    </Button>
  );
  if (settingUp && control?.setup) {
    const s = control.setup;
    const speaks = languageNames(s.languages);
    noticeFor = settingUp;
    notice = (
      <Card
        heading="Set up read aloud"
        actions={
          setup.working ? undefined : (
            <>
              <Button type="button" size="sm" onClick={() => runSetup(s)}>
                Download {formatBytes(s.bytes)}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setSettingUp(null)}>
                Not now
              </Button>
            </>
          )
        }
      >
        <p className="font-medium">Set up read aloud</p>
        <p className="text-muted-foreground">
          Read aloud speaks a reply with a voice that runs on this computer, so the text is not sent
          anywhere and no sound is kept. It needs {s.title} ({s.licence})
          {s.from ? `, from ${s.from}` : ""}: {formatBytes(s.bytes)} to download once.
          {speaks ? ` It speaks ${speaks}.` : ""}
        </p>
        {setup.working ? (
          <div className="grid gap-1">
            <Bar value={setup.fraction ?? undefined} />
            <output className="text-muted-foreground">Getting read aloud ready…</output>
          </div>
        ) : null}
        {problem && problem.id === settingUp ? (
          <p className="text-destructive">{problem.text}</p>
        ) : null}
      </Card>
    );
  } else if (setup.done && !control?.setup && settingUp) {
    noticeFor = settingUp;
    notice = (
      <Card
        heading="Read aloud"
        actions={close(() => {
          setSetupState({ working: false, fraction: null, done: false });
          setSettingUp(null);
        })}
      >
        <output>Read aloud is ready. Press Read aloud on a reply to hear it.</output>
      </Card>
    );
  } else if (problem) {
    noticeFor = problem.id;
    notice = (
      <Card heading="Read aloud" alert actions={close(() => setProblem(null))}>
        <p className="text-destructive">{problem.text}</p>
      </Card>
    );
  } else if (note) {
    noticeFor = note.id;
    notice = (
      <Card heading="Read aloud" actions={close(() => setNote(null))}>
        <output className="text-muted-foreground">{note.text}</output>
      </Card>
    );
  }

  return { available: Boolean(control), active, toggle, stop, noticeFor, notice };
}

// ---- one value for a whole screen, so every reply can have its button ---------------------------

const Context = createContext<ReadAloud | null>(null);

export function ReadAloudProvider({
  value,
  children,
}: {
  value: ReadAloud;
  children: ReactNode;
}) {
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** The screen's read-aloud state, or null where there is nothing to offer (so the button is not drawn). */
export function useReadAloudContext(): ReadAloud | null {
  const v = useContext(Context);
  return v?.available ? v : null;
}

/** What is said when the button is pressed, shown in its name and as a tooltip. */
const START = "Read this reply aloud";
const STOP = "Stop reading aloud";

/**
 * The button under a reply. Nothing plays by itself: it starts on a press and stops on a press. While it works it says so in words as well as
 * in its icon (a pulsing dot, not colour alone) and, for a long reply, which passage it is on.
 */
export function ReadAloudButton({
  id,
  text,
  className,
}: {
  id: string;
  text: string;
  className?: string;
}) {
  const ra = useReadAloudContext();
  const spoken = useMemo(() => text.trim(), [text]);
  if (!ra || !spoken) return null;
  const mine = ra.active?.id === id ? ra.active : null;
  const label = mine ? STOP : START;
  return (
    <>
      <button
        type="button"
        aria-label={label}
        aria-pressed={Boolean(mine)}
        title={label}
        onClick={() => ra.toggle(id, spoken)}
        className={cn(
          "rounded-md p-2 text-muted-foreground outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 [@media(pointer:coarse)]:p-3",
          mine && "bg-accent text-foreground",
          className,
        )}
      >
        {mine ? (
          mine.phase === "loading" && mine.part === 0 ? (
            <Loader2 className="size-4 motion-safe:animate-spin" aria-hidden="true" />
          ) : (
            <Square className="size-4" aria-hidden="true" />
          )
        ) : (
          <Volume2 className="size-4" aria-hidden="true" />
        )}
      </button>
      {mine ? (
        <output className="flex items-center gap-1.5 px-1 text-muted-foreground text-xs">
          <span
            aria-hidden="true"
            className="size-2 rounded-full bg-primary motion-safe:animate-pulse"
          />
          {mine.phase === "loading" && mine.part === 0
            ? "Getting ready to read…"
            : mine.parts > 1
              ? `Reading aloud · ${mine.part + 1} of ${mine.parts}`
              : "Reading aloud"}
        </output>
      ) : null}
    </>
  );
}

/** The old screen's whole row under a reply: the button and what it has to say. Nothing where read aloud is not offered. */
export function ReadAloudBar({ id, text }: { id: string; text: string }) {
  const ra = useReadAloudContext();
  if (!ra || !text.trim()) return null;
  return (
    <div className="-mt-1 grid gap-2">
      <div className="flex items-center">
        <ReadAloudButton id={id} text={text} />
      </div>
      <ReadAloudNotice id={id} />
    </div>
  );
}

/** The setup card, a problem or a note for this reply, drawn under its buttons. */
export function ReadAloudNotice({ id }: { id: string }) {
  const ra = useReadAloudContext();
  if (!ra || ra.noticeFor !== id) return null;
  return <div>{ra.notice}</div>;
}
