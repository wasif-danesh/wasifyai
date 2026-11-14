"use client";
// The Preview tab (mockups `preview`, `preview-empty`): the project started by its own command, inside the
// same protected area as the agent's commands, and shown here from this computer's own address. The engine
// finds the port; the page is drawn in a frame. When the program listens to more than this computer the tab
// says so, because the protected area cannot forbid that.
import type { CodeApi, CodePreview } from "@wasifyai/client";
import { ExternalLink, Monitor, Play, RotateCw, Smartphone, Square } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Input } from "../components/input";
import { Notice } from "../components/notice";
import { Spinner } from "../components/spinner";

const say = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/** A tool the command needs is not on this computer where the protected area can find it. */
function missingTool(output: string): string | null {
  const m = /(?:^|\n)(?:sh|zsh|bash): (?:\d+: )?(?:line \d+: )?(\S+): (?:command )?not found/.exec(
    output,
  );
  return m?.[1] ?? null;
}

export function PreviewPane({
  api,
  sessionId,
  project,
  tick,
  onOpenSetup,
}: {
  api: CodeApi;
  sessionId: string;
  project: string;
  /** it goes up when the project's files may have changed: the page is loaded again */
  tick: number;
  /** where Node is set up (Settings, Optional parts) */
  onOpenSetup: () => void;
}) {
  const [preview, setPreview] = useState<CodePreview | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [command, setCommand] = useState("");
  const [phone, setPhone] = useState(false);
  const [round, setRound] = useState(0); // it goes up to load the page again
  const commandId = useId();
  const read = useCallback(async () => {
    try {
      setPreview(await api.preview(sessionId));
    } catch (e) {
      setProblem(say(e, "The preview could not be read."));
    }
  }, [api, sessionId]);
  useEffect(() => {
    void read();
  }, [read]);
  // while it starts, and while it runs (it may end by itself), its state is read again
  const state = preview?.running?.state;
  useEffect(() => {
    if (state !== "starting" && state !== "running") return;
    const timer = setInterval(() => void read(), state === "starting" ? 500 : 4000);
    return () => clearInterval(timer);
  }, [state, read]);
  // a turn ended or was undone: the page is loaded again (a tool that does that by itself is not hurt)
  const first = useRef(true);
  // biome-ignore lint/correctness/useExhaustiveDependencies: only a change of the files loads it again
  useEffect(() => {
    if (first.current) first.current = false;
    else setRound((n) => n + 1);
  }, [tick]);
  const start = async (given?: string) => {
    setBusy(true);
    setProblem(null);
    try {
      setPreview(await api.startPreview(sessionId, given));
      setEditing(false);
    } catch (e) {
      setProblem(say(e, "The preview could not be started."));
    }
    setBusy(false);
  };
  const stop = async () => {
    setBusy(true);
    try {
      setPreview(await api.stopPreview(sessionId));
    } catch (e) {
      setProblem(say(e, "The preview could not be stopped."));
    }
    setBusy(false);
  };
  if (!preview) {
    return (
      <div className="grid h-full place-items-center">
        {problem ? (
          <p role="alert" className="m-0 text-sm text-destructive">
            {problem}
          </p>
        ) : (
          <Spinner className="size-4" />
        )}
      </div>
    );
  }
  const running = preview.running;
  const suggested = preview.suggested[0];
  const known = preview.command || suggested?.command || "";
  const change = () => {
    setCommand(known);
    setEditing(true);
  };
  if (!running || running.state === "ended" || editing) {
    const tool = running?.state === "ended" ? missingTool(running.output) : null;
    return (
      <div className="grid h-full place-items-center overflow-auto p-6">
        <div className="grid w-[min(100%,34rem)] justify-items-center gap-3 text-center">
          <span className="grid size-12 place-items-center rounded-full bg-muted">
            <Monitor aria-hidden="true" className="size-6 text-muted-foreground" />
          </span>
          <h3 className="m-0 text-base font-semibold">
            {running?.state === "ended" && !running.stopped
              ? "The preview has ended"
              : "Nothing is running yet"}
          </h3>
          {editing || !known ? (
            <form
              className="grid w-full gap-2 text-start"
              onSubmit={(e) => {
                e.preventDefault();
                if (command.trim()) void start(command.trim());
              }}
            >
              <label htmlFor={commandId} className="text-sm font-medium">
                The command that starts {project}
              </label>
              <Input
                id={commandId}
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                placeholder="npm run dev"
                className="font-mono"
                spellCheck={false}
                autoCapitalize="off"
                autoCorrect="off"
              />
              <p className="m-0 text-xs text-muted-foreground">
                It is given a free port as <code>$PORT</code> and <code>HOST=127.0.0.1</code>.
                {known ? "" : " Nothing in this project’s files suggests a command."}
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                <Button type="submit" disabled={busy || !command.trim()}>
                  <Play /> Start the preview
                </Button>
                {editing ? (
                  <Button type="button" variant="outline" onClick={() => setEditing(false)}>
                    Cancel
                  </Button>
                ) : null}
              </div>
            </form>
          ) : (
            <>
              <p className="m-0 text-sm text-muted-foreground">
                The preview starts your project on this computer and shows it here. For {project}{" "}
                that is <code>{known}</code>
                {preview.command ? "" : suggested ? ` (${suggested.why.replaceAll("`", "")})` : ""}.
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                <Button
                  onClick={() => void start(preview.command ? undefined : known)}
                  disabled={busy}
                >
                  {busy ? <Spinner className="size-3.5" /> : <Play />} Start the preview
                </Button>
                <Button variant="outline" onClick={change}>
                  Change the command
                </Button>
              </div>
            </>
          )}
          {running?.state === "ended" && !running.stopped ? (
            <div className="grid w-full gap-1.5 text-start">
              <p className="m-0 text-sm">
                <code>{running.command}</code> ended
                {running.exit_code === null ? "" : ` with exit code ${running.exit_code}`}.
              </p>
              {running.output ? (
                <pre className="m-0 max-h-48 overflow-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap">
                  {running.output}
                </pre>
              ) : null}
              {tool ? (
                <Notice
                  tone="warn"
                  title={`${tool} was not found`}
                  actions={
                    <Button size="sm" variant="outline" onClick={onOpenSetup}>
                      Open Optional parts
                    </Button>
                  }
                >
                  The protected area cannot read tools kept in your home folder. Node, npm and npx
                  come with the optional part “Node for coding projects”.
                </Notice>
              ) : null}
            </div>
          ) : null}
          {problem ? (
            <p role="alert" className="m-0 text-sm text-destructive">
              {problem}
            </p>
          ) : null}
          <p className="m-0 text-xs text-muted-foreground">
            It runs inside the project’s protected area. Nothing is put on the internet.
          </p>
        </div>
      </div>
    );
  }
  if (running.state === "starting") {
    return (
      <div className="grid h-full place-items-center overflow-auto p-6">
        <div className="grid w-[min(100%,34rem)] justify-items-center gap-3 text-center">
          <Spinner className="size-5" />
          <h3 className="m-0 text-base font-semibold">Starting the preview</h3>
          <p className="m-0 text-sm text-muted-foreground">
            <code>{running.command}</code>
            {running.listens_nowhere
              ? " has run for a while and listens on no port yet. It may not be a program that serves pages."
              : ""}
          </p>
          {running.output ? (
            <pre className="m-0 max-h-48 w-full overflow-auto rounded-md bg-muted p-2 text-start text-xs whitespace-pre-wrap">
              {running.output}
            </pre>
          ) : null}
          <Button variant="outline" onClick={() => void stop()} disabled={busy}>
            <Square /> Stop
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5 text-sm">
        <output className="inline-flex items-center gap-1.5 text-ok">
          <span aria-hidden="true" className="size-2 rounded-full bg-current" /> Running
        </output>
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          This computer · <code>{running.command}</code> · port {running.port}
        </span>
        <fieldset className="m-0 inline-flex rounded-md border p-0" aria-label="Size">
          <button
            type="button"
            aria-pressed={!phone}
            aria-label="Wide"
            onClick={() => setPhone(false)}
            className="rounded-s-md px-2 py-1 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-pressed:bg-accent"
          >
            <Monitor aria-hidden="true" className="size-4" />
          </button>
          <button
            type="button"
            aria-pressed={phone}
            aria-label="Phone"
            onClick={() => setPhone(true)}
            className="rounded-e-md px-2 py-1 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-pressed:bg-accent"
          >
            <Smartphone aria-hidden="true" className="size-4" />
          </button>
        </fieldset>
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="Load again"
          onClick={() => setRound((n) => n + 1)}
        >
          <RotateCw />
        </Button>
        <Button size="sm" variant="outline" onClick={() => void stop()} disabled={busy}>
          <Square /> Stop
        </Button>
        <a
          href={running.url}
          target="_blank"
          rel="noreferrer"
          aria-label="Open in your own browser"
          title="Open in your own browser"
          className="grid size-8 place-items-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ExternalLink aria-hidden="true" className="size-4" />
        </a>
      </div>
      {running.open_to_network ? (
        <div className="px-3 pt-2">
          <Notice tone="warn" title="Other computers on your network can open this too">
            This program listens on every address of this computer, not only to this computer. The
            protected area cannot forbid that. Most tools take <code>--host 127.0.0.1</code>, or
            read <code>HOST</code>, which is set for it.
          </Notice>
        </div>
      ) : null}
      <div className="grid min-h-0 flex-1 place-items-center overflow-auto bg-muted p-2">
        <iframe
          key={`${running.url}-${round}`}
          src={running.url}
          title={`The preview of ${project}`}
          // the project's own page: it may run its scripts and its forms, and nothing of the app's
          sandbox="allow-scripts allow-forms allow-same-origin allow-modals allow-popups"
          className={cn(
            "h-full border bg-background",
            phone ? "w-[390px] max-w-full rounded-xl" : "w-full rounded-md",
          )}
        />
      </div>
      <p className="m-0 border-t px-3 py-1.5 text-xs text-muted-foreground">
        Loaded again when a turn changes files.
        {running.open_to_network ? "" : " Only this computer can open it."}
      </p>
    </div>
  );
}
