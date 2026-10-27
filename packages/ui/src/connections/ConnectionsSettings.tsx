"use client";
// Settings > Connections (ADR-0069 decision 3): the switch "Let other apps use Wasify AI", the connections the person
// allowed (scopes in plain words, the approval setting, revoke, a new secret), the activity, and the exact command to
// paste for each client. A secret is shown once, when it is made.
import type {
  Connection,
  ConnectionsApi,
  FixedPortState,
  RunningJob,
  Snippets,
} from "@wasifyai/client";
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
        Paste it where the other app asks for it (the HTTP form). The stdio launcher below needs no
        secret: it reads the engine's own file.
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
    <div className="grid gap-1" aria-label="Running now">
      <h3 className="m-0 font-medium text-base">Running now</h3>
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
      <h3 className="m-0 font-medium text-base">A fixed port, for apps that connect over HTTP</h3>
      <p className="m-0 text-muted-foreground text-xs">
        Off unless you turn it on. Only this computer can reach it, and every app still needs a
        connection secret from the list below.
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
      <h3 className="m-0 font-medium text-base">A skill file for Claude Code</h3>
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

function Row({
  connection,
  api,
  onChange,
  onSecret,
}: {
  connection: Connection;
  api: ConnectionsApi;
  onChange: (c: Connection) => void;
  onSecret: (secret: string) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const approval = connection.approval.make ?? "ask";
  async function run(action: () => Promise<Connection>) {
    setError(null);
    try {
      onChange(await action());
    } catch (e) {
      setError(problem(e));
    }
  }
  return (
    <li className="grid gap-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{connection.name}</span>
        {connection.revoked ? <span className="text-muted-foreground">(revoked)</span> : null}
        <span className="text-muted-foreground text-xs">
          {connection.last_used_at
            ? `last used ${new Date(connection.last_used_at).toLocaleString()}`
            : "never used"}
        </span>
      </div>
      {!connection.revoked ? (
        <>
          <div className="flex flex-wrap gap-1">
            {PRESETS.map(([label, scopes]) => (
              <Button
                key={label}
                type="button"
                size="sm"
                variant={sameScopes(connection.scopes, scopes) ? "default" : "outline"}
                onClick={() => void run(() => api.update(connection.id, { scopes }))}
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
                      : connection.scopes.filter((s) => s !== scope);
                    void run(() => api.update(connection.id, { scopes: next }));
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
              onChange={(e) =>
                void run(() => api.update(connection.id, { approval: { make: e.target.value } }))
              }
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
            onSave={(calls_per_day) => run(() => api.update(connection.id, { calls_per_day }))}
          />
          <Folders
            label="Folders it may read files from (one per line)"
            value={connection.read_folders}
            onSave={(read_folders) => run(() => api.update(connection.id, { read_folders }))}
          />
          <Folders
            label="Folders it may save files into (one per line)"
            value={connection.write_folders}
            onSave={(write_folders) => run(() => api.update(connection.id, { write_folders }))}
          />
          <div className="flex flex-wrap gap-2">
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
              Revoke
            </Button>
          </div>
        </>
      ) : null}
      {error ? <p className="m-0 text-destructive">{error}</p> : null}
    </li>
  );
}

export function ConnectionsSettings({ api }: { api: ConnectionsApi }) {
  const nameId = useId();
  const [launcher, setLauncher] = useState<{ available: boolean; enabled: boolean } | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [snippets, setSnippets] = useState<Snippets | null>(null);
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .launcher()
      .then((l) => setLauncher({ available: l.available, enabled: l.enabled }))
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
      const l = await api.setLauncher(enabled);
      setLauncher({ available: l.available, enabled: l.enabled });
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
  }

  return (
    <section className="grid gap-3" aria-label="Connections">
      <h2 className="font-semibold text-lg">Other apps</h2>
      <p className="text-muted-foreground text-sm">
        Coding agents such as Claude Code, Codex and OpenCode can use Wasify AI as a tool: make a
        picture or a speech file, check a job, list models. Each one acts as you, with only what you
        allow here, and anything that deletes or needs your word shows a card in this window first.
      </p>
      <RunningJobs api={api} />
      {launcher ? (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={launcher.enabled}
            disabled={!launcher.available}
            onChange={(e) => void toggleLauncher(e.target.checked)}
          />
          Let other apps use Wasify AI
        </label>
      ) : null}
      {launcher?.enabled && snippets ? (
        <div className="grid gap-3">
          {CLIENTS.map(([client, key, lead]) => (
            <div key={client} className="grid gap-1">
              <p className="m-0 text-sm">
                <span className="font-medium">{client}.</span> {lead}
              </p>
              <pre className="m-0 overflow-x-auto rounded-md border bg-muted/40 p-2 text-xs">
                {snippets.snippets[key]}
              </pre>
            </div>
          ))}
          <p className="m-0 text-muted-foreground text-xs">
            The launcher is {snippets.launcher}. When this app is closed it tells the agent to open
            Wasify AI and start again.
          </p>
        </div>
      ) : null}
      {launcher?.enabled ? (
        <>
          <SkillFile api={api} />
          <FixedPort api={api} onChange={load} />
        </>
      ) : null}
      {launcher?.enabled && snippets?.snippets.claude_code_http ? (
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
      <h3 className="m-0 font-medium text-base">Connections</h3>
      <p className="m-0 text-muted-foreground text-sm">
        A connection of its own for an app that connects over HTTP, or for a second computer. The
        launcher above has one already.
      </p>
      <ul className="m-0 grid list-none gap-2 p-0">
        {connections.map((c) => (
          <Row key={c.id} connection={c} api={api} onChange={replace} onSecret={setSecret} />
        ))}
      </ul>
      {secret ? <Secret secret={secret} onDone={() => setSecret(null)} /> : null}
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
      {error ? <p className="m-0 text-destructive text-sm">{error}</p> : null}
    </section>
  );
}
