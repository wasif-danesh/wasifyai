"use client";
// The person's own agent programs, Claude Code and Codex (ADR-0107, stage H2; mockup in
// docs/spikes/coding-harness-mockup.html): the Your agent tab of the Code model button, and the same list in
// Settings › Code. Setting up and signing in happen here. The program signs in on its own page in the browser:
// nothing here reads, keeps or sends a password or a token.
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ConfirmDialog } from "../components/dialog";
import { Bar } from "../components/progress-bar";
import { formatBytes } from "../notebook/format";
import { ReadyDot } from "./marks";
import type { AgentProgram, AgentSetup, AgentsApi, ModelChoice } from "./types";

const POLL_MS = 2000; // while a sign-in waits in the browser or the programs are being set up

const say = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/** The programs and their setup, read again while something is under way. `onChange`: a program signed in, or
 * the setup ended, so the models the picker lists have changed. */
export function useAgents(api: AgentsApi | undefined, onChange?: () => void) {
  const [setup, setSetup] = useState<AgentSetup | null>(null);
  const [programs, setPrograms] = useState<AgentProgram[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const was = useRef<string>("");
  const changed = useRef(onChange);
  changed.current = onChange;
  const load = useCallback(async () => {
    if (!api) return;
    try {
      const now = await api.programs();
      setSetup(now.setup);
      setPrograms(now.programs);
      // what the picker's rows depend on: set up, and who is signed in
      const key = `${now.setup.state}|${now.programs.map((p) => `${p.id}:${p.signedIn}`).join(",")}`;
      if (was.current && was.current !== key) changed.current?.();
      was.current = key;
    } catch (e) {
      setProblem(say(e, "The agent programs could not be read."));
    }
  }, [api]);
  useEffect(() => {
    void load();
  }, [load]);
  const waiting = setup?.state === "installing" || programs.some((p) => p.signingIn);
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [waiting, load]);
  const act = useCallback(
    async (run: () => Promise<void>, fallback: string) => {
      setProblem(null);
      try {
        await run();
      } catch (e) {
        setProblem(say(e, fallback));
      }
      await load();
    },
    [load],
  );
  return { setup, programs, problem, load, act };
}

/** "Signing in…" and "Not signed in", with the one thing to do in each. */
function SignIn({
  program,
  onSignIn,
  onCancel,
}: {
  program: AgentProgram;
  onSignIn: () => void;
  onCancel: () => void;
}) {
  if (program.signingIn) {
    return (
      <div className="grid gap-2 rounded-lg border p-3 text-sm" aria-live="polite">
        <div className="flex items-center justify-between gap-2">
          <strong className="font-semibold">{program.title}</strong>
          <span className="flex items-center gap-1.5 text-muted-foreground text-xs">
            <ReadyDot state="getting" /> Signing in…
          </span>
        </div>
        <p className="m-0 text-muted-foreground">
          {program.title} opened its own sign-in page in your browser. Finish there and come back;
          this updates by itself. Wasify AI never sees your password or token.
        </p>
        <div className="flex flex-wrap gap-2">
          {program.page ? (
            <Button asChild size="sm" variant="outline">
              <a href={program.page} target="_blank" rel="noreferrer">
                Open the page again
              </a>
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="grid gap-2 rounded-lg border p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <strong className="font-semibold">{program.title}</strong>
        <span className="flex items-center gap-1.5 text-muted-foreground text-xs">
          <ReadyDot state="none" /> Not signed in
        </span>
      </div>
      <p className="m-0 text-muted-foreground">
        Sign in with your {program.account} account. {program.title} opens its own sign-in page in
        your browser.
      </p>
      <Button size="sm" className="justify-self-start" onClick={onSignIn}>
        Sign in to {program.title}
      </Button>
    </div>
  );
}

function signedLine(p: AgentProgram) {
  return ["signed in", p.plan ? `${p.plan} plan` : ""].filter(Boolean).join(" · ");
}

/** Set up the programs: the size first, then how far it is. */
function Setup({
  setup,
  onSetUp,
  compact,
}: {
  setup: AgentSetup;
  onSetUp: (bytes: number) => void;
  compact?: boolean;
}) {
  if (setup.state === "unsupported") {
    return <p className="m-0 text-muted-foreground text-sm">{setup.reason}</p>;
  }
  if (setup.state === "installing") {
    return (
      <div className="grid gap-2 text-sm" aria-live="polite">
        <span className="text-muted-foreground">
          Setting up… {setup.label}
          {setup.fraction !== null ? `, ${Math.round(setup.fraction * 100)}%` : ""}
        </span>
        <Bar value={setup.fraction ?? undefined} />
      </div>
    );
  }
  const bytes = setup.state === "not_installed" ? setup.bytes : 0;
  return (
    <div className="grid gap-2 text-sm">
      {compact ? null : (
        <>
          <strong className="font-semibold">Use your own Claude Code or Codex</strong>
          <p className="m-0 text-muted-foreground">
            Sessions can run on the agent program you already pay for, on your Claude or ChatGPT
            plan, with no key. It works inside the same sandbox as Wasify AI's agent. Setting up
            installs both programs{bytes ? `: ${formatBytes(bytes)}` : ""}.
          </p>
        </>
      )}
      {setup.state === "failed" ? (
        <p role="alert" className="m-0 text-destructive">
          {setup.message}
        </p>
      ) : null}
      <Button size="sm" className="justify-self-start" onClick={() => onSetUp(bytes)}>
        {setup.state === "failed"
          ? "Try again"
          : bytes
            ? `Set up (${formatBytes(bytes)})`
            : "Set up"}
      </Button>
      {compact ? null : (
        <p className="m-0 text-muted-foreground text-xs">
          You sign in afterwards, on each program's own page.
        </p>
      )}
    </div>
  );
}

/** The Your agent tab of the Code model button. */
export function AgentTab({
  api,
  rows,
  onPick,
  onChange,
}: {
  api: AgentsApi;
  /** the picker's rows with `place: "agent"` */
  rows: ModelChoice[];
  onPick: (c: ModelChoice) => void;
  /** the programs changed (signed in, set up): the picker reads its rows again */
  onChange: () => void;
}) {
  const a = useAgents(api, onChange);
  if (!a.setup) {
    return <p className="m-0 text-muted-foreground text-sm">{a.problem ?? "Looking…"}</p>;
  }
  return (
    <div className="grid gap-2">
      {a.problem ? (
        <p role="alert" className="m-0 text-destructive text-sm">
          {a.problem}
        </p>
      ) : null}
      {a.setup.state !== "installed" ? (
        <div className="rounded-lg border p-3">
          <Setup
            setup={a.setup}
            onSetUp={(bytes) => void a.act(() => api.setUp(bytes), "The setup could not start.")}
          />
        </div>
      ) : (
        a.programs.map((p) => {
          if (!p.signedIn) {
            return (
              <SignIn
                key={p.id}
                program={p}
                onSignIn={() =>
                  void a.act(() => api.signIn(p.id), `${p.title} could not start its sign-in.`)
                }
                onCancel={() =>
                  void a.act(() => api.cancelSignIn(p.id), "The sign-in could not be stopped.")
                }
              />
            );
          }
          const own = rows.filter((c) => c.provider === p.id);
          return (
            <ul key={p.id} className="m-0 grid list-none gap-1 p-0" aria-label={p.title}>
              <li
                className="px-3 pt-1 font-medium text-muted-foreground text-xs"
                aria-hidden="true"
              >
                {p.title} · {signedLine(p)}
              </li>
              {own.length === 0 ? (
                <li className="px-3 text-muted-foreground text-sm">
                  {p.title} did not say which models it has.
                </li>
              ) : null}
              {own.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    disabled={c.state !== "ready"}
                    aria-current={c.chosen ? "true" : undefined}
                    className={cn(
                      "grid w-full grid-cols-[minmax(0,1fr)] gap-0.5 rounded-lg px-3 py-2 text-start outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 disabled:hover:bg-transparent",
                      c.chosen && "bg-accent",
                    )}
                    onClick={() => onPick(c)}
                  >
                    <span className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate font-medium text-sm">{c.title}</span>
                      {c.tier === "recommended" ? (
                        <span className="rounded-full border px-2 py-0.5 text-xs">Recommended</span>
                      ) : null}
                    </span>
                    <span className="text-muted-foreground text-sm">{c.plain}</span>
                    <span
                      className={cn(
                        "flex items-center gap-1.5 text-xs",
                        c.chosen ? "text-ok" : "text-muted-foreground",
                      )}
                    >
                      <ReadyDot state={c.state === "ready" ? "ready" : "none"} />
                      {c.state === "ready"
                        ? `${c.chosen ? "In use · " : ""}${p.payer}`
                        : (c.unavailableReason ?? "Not available")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          );
        })
      )}
      <p className="m-0 px-1 text-muted-foreground text-xs">
        These run the program itself, on your plan. Extensions and “Ask me” are for Wasify AI's own
        agent.
      </p>
    </div>
  );
}

/** Settings › Code: the programs' sign-in, and the part that holds them. */
export function AgentPrograms({ api }: { api: AgentsApi }) {
  const a = useAgents(api);
  const [removing, setRemoving] = useState(false);
  if (!a.setup) {
    return <p className="m-0 text-muted-foreground text-sm">{a.problem ?? "Looking…"}</p>;
  }
  if (a.setup.state === "unsupported") {
    return <p className="m-0 text-muted-foreground text-sm">{a.setup.reason}</p>;
  }
  const installed = a.setup.state === "installed";
  return (
    <div className="grid gap-3 text-sm">
      <p className="m-0 text-muted-foreground">
        Your agent programs: sessions can run on these instead of a model on a key.
      </p>
      {a.problem ? (
        <p role="alert" className="m-0 text-destructive">
          {a.problem}
        </p>
      ) : null}
      <ul className="m-0 grid list-none divide-y border-y p-0">
        {installed
          ? a.programs.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="grid min-w-0 gap-0.5">
                  <strong className="font-semibold">{p.title}</strong>
                  <span className="flex items-center gap-1.5 text-xs">
                    <ReadyDot state={p.signedIn ? "ready" : p.signingIn ? "getting" : "none"} />
                    {p.signedIn
                      ? ["Signed in", p.plan ? `${p.plan} plan` : ""].filter(Boolean).join(" · ")
                      : p.signingIn
                        ? "Signing in…"
                        : "Not signed in"}
                  </span>
                  <span className="text-muted-foreground">
                    {p.signedIn
                      ? `Signed in by ${p.title} itself. To sign out, use ${p.title}.`
                      : p.signingIn
                        ? `${p.title} opened its own sign-in page in your browser. Finish there; this updates by itself.`
                        : `Opens ${p.title}'s own sign-in page in your browser.`}
                  </span>
                </div>
                <span className="flex flex-wrap gap-2">
                  {p.signingIn && p.page ? (
                    <Button asChild size="sm" variant="outline">
                      <a href={p.page} target="_blank" rel="noreferrer">
                        Open the page again
                      </a>
                    </Button>
                  ) : null}
                  {p.signingIn ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        void a.act(
                          () => api.cancelSignIn(p.id),
                          "The sign-in could not be stopped.",
                        )
                      }
                    >
                      Cancel
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant={p.signedIn ? "outline" : "default"}
                      onClick={() =>
                        void a.act(
                          () => api.signIn(p.id),
                          `${p.title} could not start its sign-in.`,
                        )
                      }
                    >
                      {p.signedIn ? "Sign in again" : `Sign in to ${p.title}`}
                    </Button>
                  )}
                </span>
              </li>
            ))
          : null}
        <li className="flex flex-wrap items-center justify-between gap-3 py-3">
          <div className="grid min-w-0 gap-0.5">
            <strong className="font-semibold">Agent programs (Claude Code, Codex)</strong>
            <span className="text-muted-foreground text-xs">
              {a.setup.state === "installed"
                ? ["Set up", a.setup.bytes ? formatBytes(a.setup.bytes) : "", a.setup.version]
                    .filter(Boolean)
                    .join(" · ")
                : a.setup.state === "installing"
                  ? "Setting up…"
                  : "Not set up"}
            </span>
          </div>
          {installed ? (
            <Button size="sm" variant="outline" onClick={() => setRemoving(true)}>
              Remove
            </Button>
          ) : (
            <div className="min-w-48">
              <Setup
                compact
                setup={a.setup}
                onSetUp={(bytes) =>
                  void a.act(() => api.setUp(bytes), "The setup could not start.")
                }
              />
            </div>
          )}
        </li>
      </ul>
      <p className="m-0 text-muted-foreground text-xs">
        Your sign-in stays with each program, in its own place on this computer. Removing the
        programs here does not sign you out.
      </p>
      {removing ? (
        <ConfirmDialog
          title="Remove the agent programs?"
          message="Claude Code and Codex are taken off this computer. Sessions on them cannot go on until they are set up again. Your sign-in stays with each program."
          onCancel={() => setRemoving(false)}
          onConfirm={() => {
            setRemoving(false);
            void a.act(() => api.remove(), "The programs could not be removed.");
          }}
        />
      ) : null}
    </div>
  );
}
