"use client";
// Settings > Connections (ADR-0069 decision 3): the switch "Let other apps use Wasify AI", the connections the person
// allowed (scopes in plain words, the approval setting, revoke, a new secret), the activity, and the exact command to
// paste for each client. A secret is shown once, when it is made.
import type { Connection, ConnectionsApi, Snippets } from "@wasifyai/client";
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
const CLIENTS: [string, string, string][] = [
  ["Claude Code", "claude_code_command", "Run this in a terminal:"],
  ["Codex", "codex_toml", "Add this to ~/.codex/config.toml:"],
  ["OpenCode", "opencode_json", "Add this to opencode.json:"],
];

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
