"use client";
// Settings > Other apps > "Tools from other apps" (ADR-0070 decisions 2, 3, 4, 6): the outside MCP
// servers the person added, what each one talks to and did, its trust, its tools after a Test, and
// the form that adds one (a program is "installing software": the name is typed again).
import type { ExternalApi, ExternalServer, ExternalTool } from "@wasifyai/client";
import { useCallback, useEffect, useId, useState } from "react";
import { Button } from "../components/button";
import { ConfirmDialog } from "../components/dialog";

const TRUSTS: [string, string][] = [
  ["ask", "asks you before every call"],
  ["blocked", "is never called"],
];

function problem(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "That did not work.";
}

function kb(n: number): string {
  return n < 1024 ? `${n} B` : `${Math.round(n / 1024)} KB`;
}

function envLines(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const eq = line.indexOf("=");
    if (eq > 0) out[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
  }
  return out;
}

function ToolRow({ tool }: { tool: ExternalTool }) {
  const readOnly = tool.annotations.readOnlyHint === true;
  const destructive = tool.annotations.destructiveHint === true;
  return (
    <li className="text-xs">
      <code>{tool.name}</code>
      {readOnly ? <span className="ml-1 text-muted-foreground">(says it only reads)</span> : null}
      {destructive ? (
        <span className="ml-1 text-muted-foreground">(says it changes things)</span>
      ) : null}
      {tool.description ? <span className="ml-1">{tool.description}</span> : null}
    </li>
  );
}

function Row({
  server,
  api,
  onChange,
  onRemoved,
}: {
  server: ExternalServer;
  api: ExternalApi;
  onChange: (s: ExternalServer) => void;
  onRemoved: (id: string) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [confirm, setConfirm] = useState(false);
  async function run(action: () => Promise<ExternalServer>) {
    setError(null);
    try {
      onChange(await action());
    } catch (e) {
      setError(problem(e));
    }
  }
  async function test() {
    setTesting(true);
    setError(null);
    try {
      const r = await api.test(server.id);
      onChange(r.server);
      if (!r.ok) setError(r.error);
    } catch (e) {
      setError(problem(e));
    } finally {
      setTesting(false);
    }
  }
  const where =
    server.transport === "http" ? server.url : [server.command, ...server.args].join(" ");
  return (
    <li className="grid gap-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{server.name}</span>
        <span className="text-muted-foreground text-xs">
          {server.transport === "http" ? `talks to ${server.host}` : `runs ${server.host}`}
        </span>
        {server.unhealthy ? (
          <span className="text-destructive text-xs">(not answering)</span>
        ) : null}
      </div>
      <code className="break-all text-muted-foreground text-xs">{where}</code>
      <p className="m-0 text-muted-foreground text-xs">
        {server.calls} calls, {kb(server.bytes_sent)} sent, {kb(server.bytes_received)} received
        {server.last_used_at ? `, last ${new Date(server.last_used_at).toLocaleString()}` : ""}
        {server.env_names.length ? `. Gets ${server.env_names.join(", ")}` : ""}
        {server.has_token ? ". Sends a token" : ""}
      </p>
      {server.last_error ? (
        <p className="m-0 text-destructive text-xs">{server.last_error}</p>
      ) : null}
      <label className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground text-xs">This server</span>
        <select
          className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
          value={server.trust}
          onChange={(e) =>
            void run(
              async () =>
                (await api.update(server.id, { trust: e.target.value as "ask" | "blocked" }))
                  .server,
            )
          }
        >
          {TRUSTS.map(([value, words]) => (
            <option key={value} value={value}>
              {words}
            </option>
          ))}
        </select>
      </label>
      {server.tools ? (
        <ul className="m-0 grid list-none gap-1 p-0" aria-label={`Tools of ${server.name}`}>
          {server.tools.map((t) => (
            <ToolRow key={t.name} tool={t} />
          ))}
        </ul>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={testing}
          onClick={() => void test()}
        >
          {testing ? "Testing…" : "Test"}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={() => setConfirm(true)}>
          Remove
        </Button>
      </div>
      {confirm ? (
        <ConfirmDialog
          title={`Remove ${server.name}?`}
          message="Its token or variables are deleted with it."
          confirmLabel="Remove"
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            api
              .remove(server.id)
              .then(() => onRemoved(server.id))
              .catch((e) => setError(problem(e)));
          }}
        />
      ) : null}
      {error ? <p className="m-0 text-destructive">{error}</p> : null}
    </li>
  );
}

export function ExternalServers({ api }: { api: ExternalApi }) {
  const id = useId();
  const [servers, setServers] = useState<ExternalServer[]>([]);
  const [transport, setTransport] = useState<"http" | "stdio">("http");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [command, setCommand] = useState("");
  const [env, setEnv] = useState("");
  const [confirmName, setConfirmName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .list()
      .then((r) => setServers(r.servers))
      .catch(() => {});
  }, [api]);
  useEffect(() => {
    load();
  }, [load]);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      const words = command.trim().split(/\s+/);
      const r = await api.add(
        transport === "http"
          ? { name: name.trim(), transport, url: url.trim(), token: token.trim() || undefined }
          : {
              name: name.trim(),
              transport,
              command: words[0] ?? "",
              args: words.slice(1),
              env: envLines(env),
              confirm_name: confirmName,
            },
      );
      setServers((ss) => [...ss, r.server]);
      setName("");
      setUrl("");
      setToken("");
      setCommand("");
      setEnv("");
      setConfirmName("");
    } catch (e) {
      setError(problem(e));
    } finally {
      setBusy(false);
    }
  }

  const ready =
    name.trim() &&
    (transport === "http" ? url.trim() : command.trim() && confirmName.trim() === name.trim());

  return (
    <section className="grid gap-3" aria-label="Tools from other apps">
      <h3 className="m-0 font-medium text-base">Tools from other apps</h3>
      <p className="m-0 text-muted-foreground text-sm">
        The assistant can use tools of other MCP servers you add here: a code host, a database, a
        chat. Each call shows you a card first, and whatever a server answers is treated as text
        from a stranger. Only you can add one; the assistant and the servers cannot.
      </p>
      <ul className="m-0 grid list-none gap-2 p-0">
        {servers.map((s) => (
          <Row
            key={s.id}
            server={s}
            api={api}
            onChange={(n) => setServers((ss) => ss.map((x) => (x.id === n.id ? n : x)))}
            onRemoved={(rid) => setServers((ss) => ss.filter((x) => x.id !== rid))}
          />
        ))}
      </ul>
      <form
        className="grid gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) void add();
        }}
      >
        <div className="flex flex-wrap items-end gap-2">
          <label htmlFor={`${id}-name`} className="grid gap-1 text-sm">
            <span>Add a server</span>
            <input
              id={`${id}-name`}
              value={name}
              maxLength={40}
              placeholder="github"
              onChange={(e) => setName(e.target.value)}
              className="h-9 min-w-40 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />
          </label>
          <label htmlFor={`${id}-kind`} className="grid gap-1 text-sm">
            <span>Kind</span>
            <select
              id={`${id}-kind`}
              className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
              value={transport}
              onChange={(e) => setTransport(e.target.value as "http" | "stdio")}
            >
              <option value="http">An address (https)</option>
              <option value="stdio">A program on this computer</option>
            </select>
          </label>
        </div>
        {transport === "http" ? (
          <div className="flex flex-wrap items-end gap-2">
            <label htmlFor={`${id}-url`} className="grid gap-1 text-sm">
              <span>Address</span>
              <input
                id={`${id}-url`}
                value={url}
                placeholder="https://mcp.example.com/mcp"
                onChange={(e) => setUrl(e.target.value)}
                className="h-9 min-w-72 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </label>
            <label htmlFor={`${id}-token`} className="grid gap-1 text-sm">
              <span>Token (optional, kept in the keychain)</span>
              <input
                id={`${id}-token`}
                type="password"
                value={token}
                autoComplete="off"
                onChange={(e) => setToken(e.target.value)}
                className="h-9 min-w-56 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </label>
          </div>
        ) : (
          <div className="grid gap-2">
            <label htmlFor={`${id}-command`} className="grid gap-1 text-sm">
              <span>Command, with its arguments</span>
              <input
                id={`${id}-command`}
                value={command}
                placeholder="npx -y @modelcontextprotocol/server-filesystem /Users/me/Notes"
                onChange={(e) => setCommand(e.target.value)}
                className="h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </label>
            <label htmlFor={`${id}-env`} className="grid gap-1 text-sm">
              <span>Variables it needs, one NAME=value per line (values go to the keychain)</span>
              <textarea
                id={`${id}-env`}
                value={env}
                rows={2}
                onChange={(e) => setEnv(e.target.value)}
                className="rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </label>
            <p className="m-0 text-sm">
              This starts a program on your computer, as you, with only the variables above, in a
              folder of its own under the app's data. Adding it is installing software: type its
              name to confirm.
            </p>
            <label htmlFor={`${id}-confirm`} className="grid gap-1 text-sm">
              <span>Type the name to confirm</span>
              <input
                id={`${id}-confirm`}
                value={confirmName}
                onChange={(e) => setConfirmName(e.target.value)}
                className="h-9 min-w-40 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </label>
          </div>
        )}
        <div>
          <Button type="submit" variant="outline" disabled={busy || !ready}>
            Add
          </Button>
        </div>
      </form>
      {error ? <p className="m-0 text-destructive text-sm">{error}</p> : null}
    </section>
  );
}
