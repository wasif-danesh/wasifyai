"use client";
// Settings › Other apps, the first card: "Apps that can use Wasify AI" (ADR-0069 decision 3; the Settings mockup approved
// on 2026-11-15). The switch "Let other apps use Wasify AI" turns on the launcher that Claude Code, Codex and OpenCode
// start; "Connect an app" gives that app's one setup step. What the apps may do is one line, with Change for the
// details (scopes in plain words, the approval setting, the daily quota, folders). Connections of their own (a secret,
// for an app that connects over HTTP or a second computer), the fixed port and the skill file sit under "For experts";
// removed connections are hidden until asked for. A secret is shown once, when it is made.
import type {
  Connection,
  ConnectionsApi,
  FixedPortState,
  LauncherState,
  RunningJob,
  Snippets,
} from "@wasifyai/client";
import { ArrowDownLeft } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";
import { Button } from "../components/button";

const SCOPE_WORDS: Record<string, string> = {
  make: "make pictures, videos, speech and music",
  models: "list and get models",
  library: "see and change your creations (private)",
  notebooks: "read and change your notebooks (private)",
  voices: "list, add and delete your voices",
};
const CHOOSABLE = ["make", "models", "library", "notebooks", "voices"];
const APPROVALS: [string, string][] = [
  ["ask", "asks you before making things"],
  ["ask_costly", "asks only for things that take a while or leave this computer"],
  ["auto", "makes things without asking"],
];
/** Scope presets (ADR-0069 stage M2): what a connection may do, in one click. */
const PRESETS: [string, string[]][] = [
  ["Make things", ["make", "models"]],
  ["Make and use my library", ["make", "models", "library", "notebooks", "voices"]],
  ["Everything", ["make", "models", "library", "notebooks", "voices"]],
];
const CLIENTS: [string, string, string][] = [
  ["Claude Code", "claude_code_command", "Run this in a terminal:"],
  ["Codex", "codex_toml", "Add this to ~/.codex/config.toml:"],
  ["OpenCode", "opencode_json", "Add this to opencode.json:"],
];

const JOBS_EVERY_MS = 3000;

function problem(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "That did not work.";
}

function Secret({ secret, onDone }: { secret: string; onDone: () => void }) {
  return (
    <div className="grid gap-2 rounded-lg border bg-accent/40 p-3 text-sm">
      <p className="m-0 font-medium">This is the connection's secret. It is shown once.</p>
      <code className="break-all rounded bg-background p-2 font-mono text-xs">{secret}</code>
      <p className="m-0 text-muted-foreground text-xs">
        Paste it where the other app asks for it. Apps connected with "Connect an app" need no
        secret.
      </p>
      <div>
        <Button type="button" size="sm" variant="outline" onClick={onDone}>
          I have copied it
        </Button>
      </div>
    </div>
  );
}

function sameScopes(a: string[], b: string[]): boolean {
  const x = new Set(a.filter((s) => s !== "read"));
  const y = new Set(b.filter((s) => s !== "read"));
  return x.size === y.size && [...x].every((s) => y.has(s));
}

/** The folders a connection may read from or write into (spike S2): full paths, one per line. */
function Folders({
  label,
  value,
  onSave,
}: {
  label: string;
  value: string[];
  onSave: (folders: string[]) => Promise<void>;
}) {
  const id = useId();
  const [text, setText] = useState(value.join("\n"));
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const changed = lines.join("\n") !== value.join("\n");
  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-muted-foreground text-xs">
        {label}
      </label>
      <textarea
        id={id}
        value={text}
        rows={2}
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
        className="min-h-12 w-full rounded-md border border-input bg-transparent px-3 py-1 font-mono text-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      />
      {changed ? (
        <div>
          <Button type="button" size="sm" variant="outline" onClick={() => void onSave(lines)}>
            Save folders
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** The daily quota (ADR-0069 decision 10): how many tool calls a day, saved on blur or Enter. */
function Quota({ value, onSave }: { value: number; onSave: (n: number) => void }) {
  const id = useId();
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  function save() {
    const n = Number.parseInt(text, 10);
    if (Number.isFinite(n) && n >= 1 && n !== value) onSave(n);
    else setText(String(value));
  }
  return (
    <label htmlFor={id} className="flex flex-wrap items-center gap-2">
      <span className="text-muted-foreground text-xs">Tool calls a day, at most</span>
      <input
        id={id}
        type="number"
        min={1}
        max={100000}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            save();
          }
        }}
        className="h-8 w-24 rounded-md border border-input bg-transparent px-2 text-sm"
      />
      <span className="text-muted-foreground text-xs">(it runs one job at a time)</span>
    </label>
  );
}

/** What is running now and who started it (ADR-0069 decision 10: jobs are labelled and the person can stop them). */
function RunningJobs({ api }: { api: ConnectionsApi }) {
  const [jobs, setJobs] = useState<RunningJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .jobs()
        .then((r) => {
          if (alive) setJobs(r.jobs);
        })
        .catch(() => {});
    tick();
    const timer = setInterval(tick, JOBS_EVERY_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [api]);
  if (jobs.length === 0) return null;
  async function stop(job: RunningJob) {
    setError(null);
    try {
      await api.cancelJob(job.job_id);
      setJobs((js) => js.filter((j) => j.job_id !== job.job_id));
    } catch (e) {
      setError(problem(e));
    }
  }
  return (
    <div className="grid gap-1 border-t px-4 py-2.5" aria-label="Running now">
      <h4 className="m-0 font-medium text-sm">Running now</h4>
      <ul className="m-0 grid list-none gap-1 p-0">
        {jobs.map((j) => (
          <li key={j.job_id} className="flex flex-wrap items-center gap-2 text-sm">
            <span>
              {j.action_id}
              {j.from ? ` from ${j.from}` : ""}
            </span>
            <span className="text-muted-foreground text-xs">{Math.round(j.seconds)} s</span>
            {j.cancellable ? (
              <Button type="button" size="sm" variant="outline" onClick={() => void stop(j)}>
                Stop
              </Button>
            ) : (
              <span className="text-muted-foreground text-xs">(finishes on its own)</span>
            )}
          </li>
        ))}
      </ul>
      {error ? <p className="m-0 text-destructive text-sm">{error}</p> : null}
    </div>
  );
}

/** The opt-in fixed HTTP port (ADR-0069 decision 2) for a client that cannot run the launcher. */
function FixedPort({
  api,
  onChange,
}: {
  api: ConnectionsApi;
  onChange: () => void;
}) {
  const id = useId();
  const [state, setState] = useState<FixedPortState | null>(null);
  const [port, setPort] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .fixedPort()
      .then((s) => {
        setState(s);
        if (s.port) setPort(String(s.port));
      })
      .catch(() => setState({ available: false, port: null, url: null }));
  }, [api]);
  if (!state?.available) return null;
  async function apply(next: number | null) {
    setError(null);
    try {
      const s = await api.setFixedPort(next);
      setState(s);
      setPort(s.port ? String(s.port) : "");
      onChange();
    } catch (e) {
      setError(problem(e));
    }
  }
  return (
    <div className="grid gap-1" aria-label="Fixed port">
      <h4 className="m-0 font-medium text-sm">A fixed port, for apps that connect over HTTP</h4>
      <p className="m-0 text-muted-foreground text-xs">
        Off unless you turn it on. Only this computer can reach it, and every app still needs the
        secret of a connection of its own, above.
      </p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const n = Number.parseInt(port, 10);
          if (Number.isFinite(n)) void apply(n);
        }}
      >
        <label htmlFor={id} className="grid gap-1 text-sm">
          <span>Port</span>
          <input
            id={id}
            type="number"
            min={1024}
            max={65535}
            value={port}
            placeholder="8765"
            onChange={(e) => setPort(e.target.value)}
            className="h-9 w-28 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
        </label>
        <Button type="submit" variant="outline" disabled={!port.trim()}>
          {state.port ? "Change" : "Turn on"}
        </Button>
        {state.port ? (
          <Button type="button" variant="outline" onClick={() => void apply(null)}>
            Turn off
          </Button>
        ) : null}
      </form>
      {state.url ? (
        <p className="m-0 text-sm">
          Listening at <code>{state.url}</code>.
        </p>
      ) : null}
      {error ? <p className="m-0 text-destructive text-sm">{error}</p> : null}
    </div>
  );
}

/** The skill file for Claude Code: words that tell an agent how to use the tools well, made from the catalogue. */
function SkillFile({ api }: { api: ConnectionsApi }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function show() {
    setError(null);
    try {
      setText(await api.skill());
    } catch (e) {
      setError(problem(e));
    }
  }
  return (
    <div className="grid gap-1" aria-label="Skill file">
      <h4 className="m-0 font-medium text-sm">A skill file for Claude Code</h4>
      <p className="m-0 text-muted-foreground text-xs">
        Optional. Save it as <code>.claude/skills/wasify-ai/SKILL.md</code> in a project (or under{" "}
        <code>~/.claude/skills/</code>) and Claude Code knows when and how to use Wasify AI. It is
        made from what this app can do, so make it again after an update.
      </p>
      {text === null ? (
        <div>
          <Button type="button" size="sm" variant="outline" onClick={() => void show()}>
            Show the skill file
          </Button>
        </div>
      ) : (
        <pre className="m-0 max-h-80 overflow-auto rounded-md border bg-muted/40 p-2 text-xs">
          {text}
        </pre>
      )}
      {error ? <p className="m-0 text-destructive text-sm">{error}</p> : null}
    </div>
  );
}

/** What a connection may do, in one line. */
export function canDo(c: Connection): string {
  const scopes = new Set(c.scopes.filter((x) => x !== "read"));
  const mine = ["library", "notebooks", "voices"].some((x) => scopes.has(x));
  const what = scopes.has("make")
    ? mine
      ? "Can make things and use your library"
      : "Can make things"
    : mine
      ? "Can use your library"
      : scopes.has("models")
        ? "Can list models"
        : "Can only look";
  const ask: Record<string, string> = {
    ask: "asks before it makes something",
    ask_costly: "asks for slow or cloud jobs",
    auto: "makes things without asking",
  };
  return `${what}; ${ask[c.approval.make ?? "ask"] ?? ask.ask}.`;
}

function used(c: Connection): string {
  return c.last_used_at ? `Used ${new Date(c.last_used_at).toLocaleDateString()}.` : "Never used.";
}

/** The details of what a connection may do: presets, scopes, the approval setting, the quota and folders. */
type Update = Parameters<ConnectionsApi["update"]>[1];

function Permissions({
  connection,
  run,
  update,
}: {
  connection: Connection;
  run: (action: () => Promise<Connection>) => Promise<void>;
  update: (body: Update) => Promise<Connection>;
}) {
  const approval = connection.approval.make ?? "ask";
  return (
    <div className="grid gap-2 border-t bg-muted/30 px-4 py-3 text-sm">
      <div className="flex flex-wrap gap-1">
        {PRESETS.map(([label, scopes]) => (
          <Button
            key={label}
            type="button"
            size="sm"
            variant={sameScopes(connection.scopes, scopes) ? "default" : "outline"}
            onClick={() => void run(() => update({ scopes }))}
          >
            {label}
          </Button>
        ))}
      </div>
      <fieldset className="m-0 grid gap-1 border-0 p-0">
        <legend className="text-muted-foreground text-xs">It may</legend>
        {CHOOSABLE.map((scope) => (
          <label key={scope} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={connection.scopes.includes(scope)}
              onChange={(e) => {
                const next = e.target.checked
                  ? [...connection.scopes, scope]
                  : connection.scopes.filter((x) => x !== scope);
                void run(() => update({ scopes: next }));
              }}
            />
            {SCOPE_WORDS[scope]}
          </label>
        ))}
      </fieldset>
      <label className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground text-xs">Before it makes something, it</span>
        <select
          className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
          value={approval}
          onChange={(e) => void run(() => update({ approval: { make: e.target.value } }))}
        >
          {APPROVALS.map(([value, words]) => (
            <option key={value} value={value}>
              {words}
            </option>
          ))}
        </select>
      </label>
      <p className="m-0 text-muted-foreground text-xs">
        Deleting and anything that needs your word always ask you, whatever this says.
      </p>
      <Quota
        value={connection.calls_per_day}
        onSave={(calls_per_day) => run(() => update({ calls_per_day }))}
      />
      <Folders
        label="Folders it may read files from (one per line)"
        value={connection.read_folders}
        onSave={(read_folders) => run(() => update({ read_folders }))}
      />
      <Folders
        label="Folders it may save files into (one per line)"
        value={connection.write_folders}
        onSave={(write_folders) => run(() => update({ write_folders }))}
      />
    </div>
  );
}

/** One connection: its name, one line on what it may do, and Change (the details) or, for one of its own, Remove. */
function Row({
  connection,
  title,
  api,
  onChange,
  onSecret,
}: {
  connection: Connection;
  title?: string;
  api: ConnectionsApi;
  onChange: (c: Connection) => void;
  onSecret?: (secret: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(action: () => Promise<Connection>) {
    setError(null);
    try {
      onChange(await action());
    } catch (e) {
      setError(problem(e));
    }
  }
  const name = title ?? connection.name;
  if (connection.revoked) {
    return (
      <li className="px-4 py-2.5 text-muted-foreground text-sm">
        {connection.name}
        <span className="block text-xs">Removed. {used(connection)}</span>
      </li>
    );
  }
  return (
    <li aria-label={name}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
        <span className="min-w-0 flex-1">
          <span className="font-medium">{name}</span>
          <span className="block text-muted-foreground text-xs">
            {canDo(connection)} {used(connection)}
          </span>
        </span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-expanded={open}
          aria-label={`Change what ${name} may do`}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "Done" : "Change"}
        </Button>
        {onSecret ? (
          <>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() =>
                void run(async () => {
                  const r = await api.rotate(connection.id);
                  onSecret(r.secret);
                  return r.connection;
                })
              }
            >
              New secret
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void run(() => api.revoke(connection.id))}
            >
              Remove
            </Button>
          </>
        ) : null}
      </div>
      {open ? (
        <Permissions
          connection={connection}
          run={run}
          update={(body) => api.update(connection.id, body)}
        />
      ) : null}
      {error ? <p className="m-0 px-4 pb-2 text-destructive text-sm">{error}</p> : null}
    </li>
  );
}

/** "Connect an app": which app, then its one setup step. */
function ConnectApp({ snippets }: { snippets: Snippets | null }) {
  const [open, setOpen] = useState(false);
  const [client, setClient] = useState<string | null>(null);
  const chosen = CLIENTS.find(([name]) => name === client);
  return (
    <li className="grid gap-2 px-4 py-2.5 text-sm">
      <div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          + Connect an app
        </Button>
      </div>
      {open ? (
        <fieldset className="m-0 grid gap-2 border-0 p-0">
          <legend className="mb-2 p-0 font-medium text-sm">Which app?</legend>
          <div className="flex flex-wrap gap-2">
            {CLIENTS.map(([name]) => (
              <Button
                key={name}
                type="button"
                size="sm"
                variant={client === name ? "default" : "outline"}
                aria-pressed={client === name}
                onClick={() => setClient(name)}
              >
                {name}
              </Button>
            ))}
          </div>
          {chosen && snippets ? (
            <div className="grid gap-1">
              <p className="m-0 text-sm">{chosen[2]}</p>
              <pre className="m-0 overflow-x-auto rounded-md border bg-muted/40 p-2 text-xs">
                {snippets.snippets[chosen[1]]}
              </pre>
              <p className="m-0 text-muted-foreground text-xs">
                Then start {chosen[0]} again. If Wasify AI is closed, it asks you to open it.
              </p>
            </div>
          ) : null}
          <p className="m-0 text-muted-foreground text-xs">
            Another app, or a second computer? Use For experts below.
          </p>
        </fieldset>
      ) : null}
    </li>
  );
}

export function ConnectionsSettings({ api }: { api: ConnectionsApi }) {
  const nameId = useId();
  const [launcher, setLauncher] = useState<LauncherState | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [snippets, setSnippets] = useState<Snippets | null>(null);
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showRemoved, setShowRemoved] = useState(false);
  const [experts, setExperts] = useState(false);

  const load = useCallback(() => {
    api
      .launcher()
      .then(setLauncher)
      .catch(() => setLauncher({ available: false, enabled: false }));
    api
      .list()
      .then((r) => setConnections(r.connections))
      .catch(() => {});
    api
      .snippets()
      .then(setSnippets)
      .catch(() => {});
  }, [api]);
  useEffect(() => {
    load();
  }, [load]);

  async function toggleLauncher(enabled: boolean) {
    setError(null);
    try {
      setLauncher(await api.setLauncher(enabled));
    } catch (e) {
      setError(problem(e));
    }
  }

  async function create() {
    const n = name.trim();
    if (!n) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.create({ name: n });
      setConnections((cs) => [...cs, r.connection]);
      setSecret(r.secret);
      setName("");
    } catch (e) {
      setError(problem(e));
    } finally {
      setBusy(false);
    }
  }

  function replace(c: Connection) {
    setConnections((cs) => cs.map((x) => (x.id === c.id ? c : x)));
    setLauncher((l) => (l?.connection?.id === c.id ? { ...l, connection: c } : l));
  }

  const own = connections.filter((c) => c.kind !== "launcher" && !c.revoked);
  const removed = connections.filter((c) => c.kind !== "launcher" && c.revoked);
  const on = Boolean(launcher?.enabled);

  return (
    <section className="rounded-xl border bg-card" aria-label="Apps that can use Wasify AI">
      <div className="flex items-start gap-3 px-4 pt-3.5 pb-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
          <ArrowDownLeft aria-hidden="true" className="size-4" />
        </span>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <h3 className="m-0 font-medium text-base">Apps that can use Wasify AI</h3>
          <p className="m-0 text-muted-foreground text-sm">
            Claude Code, Codex and OpenCode can ask Wasify AI to make a picture, a voice file or a
            video. Each app does only what you allow, and deleting always asks you here first.
          </p>
        </div>
        {launcher?.available ? (
          <label className="flex shrink-0 items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={on}
              onChange={(e) => void toggleLauncher(e.target.checked)}
            />
            <span>
              <span className="sr-only">Let other apps use Wasify AI</span>
              <span aria-hidden="true">{on ? "On" : "Off"}</span>
            </span>
          </label>
        ) : null}
      </div>
      <ul className="m-0 list-none divide-y border-t p-0">
        {!on ? (
          <li className="px-4 py-2.5 text-muted-foreground text-sm">
            Off: Claude Code, Codex and OpenCode cannot reach Wasify AI.
          </li>
        ) : (
          <>
            {launcher?.connection ? (
              <Row
                connection={launcher.connection}
                title="Every app you connect"
                api={api}
                onChange={replace}
              />
            ) : null}
            <ConnectApp snippets={snippets} />
          </>
        )}
        {own.map((c) => (
          <Row key={c.id} connection={c} api={api} onChange={replace} onSecret={setSecret} />
        ))}
      </ul>
      <RunningJobs api={api} />
      {secret ? (
        <div className="px-4 pb-3">
          <Secret secret={secret} onDone={() => setSecret(null)} />
        </div>
      ) : null}
      {showRemoved && removed.length ? (
        <ul className="m-0 list-none divide-y border-t p-0" aria-label="Removed connections">
          {removed.map((c) => (
            <Row key={c.id} connection={c} api={api} onChange={replace} />
          ))}
        </ul>
      ) : null}
      {experts ? (
        <div className="grid gap-4 border-t px-4 py-3" aria-label="For experts">
          <div className="grid gap-1">
            <h4 className="m-0 font-medium text-sm">A connection of its own</h4>
            <p className="m-0 text-muted-foreground text-xs">
              For an app that connects over HTTP, or a second computer. It gets a secret, shown
              once.
            </p>
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void create();
              }}
            >
              <label htmlFor={nameId} className="grid gap-1 text-sm">
                <span>New connection</span>
                <input
                  id={nameId}
                  value={name}
                  maxLength={60}
                  placeholder="Codex on my laptop"
                  onChange={(e) => setName(e.target.value)}
                  className="h-9 min-w-64 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                />
              </label>
              <Button type="submit" variant="outline" disabled={busy || !name.trim()}>
                Add
              </Button>
            </form>
          </div>
          {on ? <FixedPort api={api} onChange={load} /> : null}
          {on && snippets?.snippets.claude_code_http ? (
            <div className="grid gap-1">
              <p className="m-0 text-sm">
                <span className="font-medium">Over HTTP.</span> With a connection secret in{" "}
                <code>WASIFY_MCP_SECRET</code>, Claude Code takes:
              </p>
              <pre className="m-0 overflow-x-auto rounded-md border bg-muted/40 p-2 text-xs">
                {snippets.snippets.claude_code_http}
              </pre>
            </div>
          ) : null}
          {on ? <SkillFile api={api} /> : null}
          {on && snippets ? (
            <p className="m-0 text-muted-foreground text-xs">
              The launcher is {snippets.launcher}.
            </p>
          ) : null}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t px-4 py-2.5">
        {removed.length ? (
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-xs"
            aria-expanded={showRemoved}
            onClick={() => setShowRemoved((v) => !v)}
          >
            {showRemoved
              ? "Hide removed connections"
              : `Show ${removed.length} removed connection${removed.length === 1 ? "" : "s"}`}
          </Button>
        ) : null}
        <Button
          type="button"
          variant="link"
          className="h-auto p-0 text-xs"
          aria-expanded={experts}
          onClick={() => setExperts((v) => !v)}
        >
          {experts
            ? "Hide For experts"
            : "For experts: a connection of its own, a fixed port, a skill file"}
        </Button>
      </div>
      {error ? <p className="m-0 px-4 pb-3 text-destructive text-sm">{error}</p> : null}
    </section>
  );
}
