"use client";
// The Terminal tab (mockup `terminal`): the person's own terminal in the project. It is a real shell that the
// engine runs inside the same protected area as the agent's commands, so it can change only this project and
// reaches the internet only to install packages. What is typed goes to the engine; what the shell prints
// comes back as a stream. The picture of the terminal is xterm.js, loaded when the tab is first opened.
import type { CodeApi, CodeTerminal } from "@wasifyai/client";
import { Info, Plus, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Spinner } from "../components/spinner";
import { XTERM_CSS } from "./xterm-css";

const NOTE_KEY = "wasify.code.terminal-note";

function bytes(base64: string): Uint8Array {
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** One terminal on the screen, fed by its stream. */
function Screen({
  api,
  sessionId,
  terminal,
  shown,
  onEnded,
}: {
  api: CodeApi;
  sessionId: string;
  terminal: CodeTerminal;
  shown: boolean;
  onEnded: (code: number | null) => void;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  const fit = useRef<(() => void) | null>(null);
  const ended = useRef(onEnded);
  ended.current = onEnded;
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const stop = new AbortController();
    let gone = false;
    let dispose = () => {};
    void (async () => {
      const [{ Terminal }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
      if (gone) return;
      const style = getComputedStyle(el);
      const term = new Terminal({
        fontFamily: style.fontFamily,
        fontSize: 13,
        cursorBlink: true,
        convertEol: false,
        scrollback: 5000,
        theme: {
          background: style.backgroundColor,
          foreground: style.color,
          cursor: style.color,
        },
      });
      const fitter = new FitAddon();
      term.loadAddon(fitter);
      term.open(el);
      const sized = () => {
        try {
          fitter.fit();
        } catch {
          // not on the screen yet
        }
      };
      sized();
      fit.current = sized;
      let last = { cols: term.cols, rows: term.rows };
      void api.terminalSize(sessionId, terminal.id, term.cols, term.rows).catch(() => {});
      const onSize = term.onResize(({ cols, rows }) => {
        if (cols === last.cols && rows === last.rows) return;
        last = { cols, rows };
        void api.terminalSize(sessionId, terminal.id, cols, rows).catch(() => {});
      });
      // what is typed is sent in order: one call at a time, the rest waits and goes together
      let waiting = "";
      let sending = false;
      const flush = async () => {
        if (sending) return;
        sending = true;
        while (waiting && !gone) {
          const data = waiting;
          waiting = "";
          try {
            await api.terminalInput(sessionId, terminal.id, data);
          } catch {
            break; // the terminal has ended
          }
        }
        sending = false;
      };
      const onData = term.onData((data) => {
        waiting += data;
        void flush();
      });
      const watch = new ResizeObserver(sized);
      watch.observe(el);
      dispose = () => {
        watch.disconnect();
        onData.dispose();
        onSize.dispose();
        term.dispose();
      };
      let after = 0;
      while (!gone) {
        try {
          for await (const event of api.terminalEvents(
            sessionId,
            terminal.id,
            after,
            stop.signal,
          )) {
            if (gone) return;
            after = event.seq;
            if (event.data !== undefined) term.write(bytes(event.data));
            else {
              term.write("\r\n\x1b[2m[This terminal has ended.]\x1b[0m\r\n");
              ended.current(event.exit_code);
              return;
            }
          }
        } catch {
          // the connection dropped, or the terminal is gone
        }
        if (gone) return;
        await new Promise((r) => setTimeout(r, 1000));
        try {
          const still = await api.terminals(sessionId);
          if (!still.some((t) => t.id === terminal.id && !t.ended)) {
            ended.current(null);
            return;
          }
        } catch {
          // try the stream again
        }
      }
    })();
    return () => {
      gone = true;
      stop.abort();
      dispose();
    };
  }, [api, sessionId, terminal.id]);
  useEffect(() => {
    if (shown) fit.current?.();
  }, [shown]);
  return (
    <div
      ref={box}
      // the terminal takes its colours and its letters from here
      className={cn(
        "min-h-0 flex-1 overflow-hidden bg-muted px-2 py-1.5 font-mono text-foreground",
        shown ? "block" : "hidden",
      )}
      aria-label="Terminal"
      role="group"
    />
  );
}

/** The Terminal tab: the note about its limits, the open terminals, and "New". */
export function TerminalPane({
  api,
  sessionId,
  project,
}: {
  api: CodeApi;
  sessionId: string;
  project: string;
}) {
  const [terminals, setTerminals] = useState<CodeTerminal[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [note, setNote] = useState(() => {
    try {
      return localStorage.getItem(NOTE_KEY) !== "hidden";
    } catch {
      return true;
    }
  });
  const open = useCallback(async () => {
    setOpening(true);
    try {
      const made = await api.openTerminal(sessionId, 80, 24);
      setTerminals((all) => [...(all ?? []), made]);
      setCurrent(made.id);
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error && e.message ? e.message : "The terminal could not be opened.");
    }
    setOpening(false);
  }, [api, sessionId]);
  // the terminals that are already open in this session (the tab was closed and opened again)
  useEffect(() => {
    let gone = false;
    api
      .terminals(sessionId)
      .then((found) => {
        if (gone) return;
        const live = found.filter((t) => !t.ended);
        setTerminals(live);
        setCurrent(live[0]?.id ?? null);
      })
      .catch(() => {
        if (!gone) setTerminals([]);
      });
    return () => {
      gone = true;
    };
  }, [api, sessionId]);
  const close = async (id: string) => {
    try {
      await api.closeTerminal(sessionId, id);
    } catch {
      // it is gone already
    }
    setTerminals((all) => {
      const left = (all ?? []).filter((t) => t.id !== id);
      setCurrent((c) => (c === id ? (left[0]?.id ?? null) : c));
      return left;
    });
  };
  const hide = () => {
    setNote(false);
    try {
      localStorage.setItem(NOTE_KEY, "hidden");
    } catch {
      // it is hidden until the app is opened again
    }
  };
  return (
    <div className="flex h-full min-h-0 flex-col">
      <style>{XTERM_CSS}</style>
      {note ? (
        <div className="m-3 mb-0 grid gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2.5 text-sm">
          <h3 className="m-0 flex items-center gap-2 text-sm font-semibold">
            <Info aria-hidden="true" className="size-4 shrink-0" /> This terminal has the same
            limits as the agent
          </h3>
          <p className="m-0 text-muted-foreground">
            It can change only this project’s folder, cannot read your other folders, and reaches
            the internet only to install packages. Because of those limits <code>ps</code>,{" "}
            <code>top</code> and <code>sudo</code> do not work here. Your own start-up files are not
            read.
          </p>
          <div>
            <Button size="sm" variant="ghost" onClick={hide}>
              Hide this note
            </Button>
          </div>
        </div>
      ) : null}
      <div className="flex items-center gap-1 px-3 py-1.5 text-xs text-muted-foreground">
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" role="tablist">
          {(terminals ?? []).map((t, n) => (
            <span
              key={t.id}
              className={cn(
                "inline-flex shrink-0 items-center rounded-md border",
                t.id === current && "bg-accent text-foreground",
              )}
            >
              <button
                type="button"
                role="tab"
                aria-selected={t.id === current}
                onClick={() => setCurrent(t.id)}
                className="rounded-s-md px-2 py-0.5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Terminal {n + 1}
                {t.ended ? " · ended" : ""}
              </button>
              <button
                type="button"
                aria-label={`Close terminal ${n + 1}`}
                onClick={() => void close(t.id)}
                className="rounded-e-md px-1 py-0.5 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X aria-hidden="true" className="size-3" />
              </button>
            </span>
          ))}
          {terminals?.length ? null : <span>Your terminal · {project}</span>}
        </div>
        <Button size="sm" variant="ghost" onClick={() => void open()} disabled={opening}>
          {opening ? <Spinner className="size-3.5" /> : <Plus />} New
        </Button>
      </div>
      {problem ? (
        <p role="alert" className="m-0 px-3 pb-2 text-sm text-destructive">
          {problem}
        </p>
      ) : null}
      {terminals === null ? (
        <div className="grid flex-1 place-items-center">
          <Spinner className="size-4" />
        </div>
      ) : terminals.length === 0 ? (
        <div className="grid flex-1 place-items-center p-6 text-center">
          <div className="grid justify-items-center gap-3">
            <p className="m-0 max-w-[36ch] text-sm text-muted-foreground">
              A terminal of your own in {project}. Run the project’s tests, install what it needs,
              or look around. The agent does not see what you type here.
            </p>
            <Button onClick={() => void open()} disabled={opening}>
              Open a terminal
            </Button>
          </div>
        </div>
      ) : (
        (terminals ?? []).map((t) => (
          <Screen
            key={t.id}
            api={api}
            sessionId={sessionId}
            terminal={t}
            shown={t.id === current}
            onEnded={(code) =>
              setTerminals((all) =>
                (all ?? []).map((x) =>
                  x.id === t.id ? { ...x, ended: true, exit_code: code } : x,
                ),
              )
            }
          />
        ))
      )}
    </div>
  );
}
