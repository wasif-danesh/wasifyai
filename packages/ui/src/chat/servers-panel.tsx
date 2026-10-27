"use client";
import { useAui } from "@assistant-ui/react";
// Outside servers in the box (ADR-0070 decision 10, stage C3): what the servers the person connected offer to read (a
// resource becomes a document attached to the next message) and their prompts (a template put in the box, with its
// arguments asked for first). The panel is a notice above the box; nothing is sent until the person sends.
import type { ExternalPrompt, ExternalResource, UploadedAttachment } from "@wasifyai/client";
import { useCallback, useEffect, useId, useState } from "react";
import { Button } from "../components/button";

/** What the app gives the box about outside servers (absent where the engine has no MCP client). */
export type ExternalControl = {
  /** the servers that can be used now, by id and name */
  servers: () => Promise<{ id: string; name: string }[]>;
  resources: (serverId: string) => Promise<ExternalResource[]>;
  /** reads the resource on the engine and keeps it as a document; the box attaches it */
  attachResource: (serverId: string, uri: string) => Promise<UploadedAttachment>;
  prompts: (serverId: string) => Promise<ExternalPrompt[]>;
  promptText: (serverId: string, name: string, args: Record<string, string>) => Promise<string>;
};

type Loaded = {
  id: string;
  name: string;
  resources: ExternalResource[];
  prompts: ExternalPrompt[];
  error: string;
};

function problem(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "That did not work.";
}

function PromptRow({
  server,
  prompt,
  control,
  onInsert,
  onError,
}: {
  server: Loaded;
  prompt: ExternalPrompt;
  control: ExternalControl;
  onInsert: (text: string) => void;
  onError: (text: string) => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [args, setArgs] = useState<Record<string, string>>({});
  const needs = prompt.arguments.filter((a) => a.required);
  async function use() {
    try {
      onInsert(await control.promptText(server.id, prompt.name, args));
      setOpen(false);
    } catch (e) {
      onError(problem(e));
    }
  }
  const ready = needs.every((a) => (args[a.name] ?? "").trim());
  return (
    <li className="grid gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <span>{prompt.title}</span>
        {prompt.description ? (
          <span className="text-muted-foreground text-xs">{prompt.description}</span>
        ) : null}
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => (prompt.arguments.length ? setOpen((o) => !o) : void use())}
        >
          Use
        </Button>
      </div>
      {open ? (
        <form
          className="grid gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            if (ready) void use();
          }}
        >
          {prompt.arguments.map((a) => (
            <label key={a.name} htmlFor={`${id}-${a.name}`} className="grid gap-0.5 text-xs">
              <span>
                {a.name}
                {a.required ? "" : " (optional)"}
                {a.description ? `: ${a.description}` : ""}
              </span>
              <input
                id={`${id}-${a.name}`}
                value={args[a.name] ?? ""}
                onChange={(e) => setArgs((s) => ({ ...s, [a.name]: e.target.value }))}
                className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
              />
            </label>
          ))}
          <div>
            <Button type="submit" size="sm" variant="outline" disabled={!ready}>
              Put it in the box
            </Button>
          </div>
        </form>
      ) : null}
    </li>
  );
}

/** The panel: one block per server with its resources (Attach) and prompts (Use). */
export function ServersPanel({
  control,
  onAttach,
  onInsert,
  onClose,
}: {
  control: ExternalControl;
  /** a resource read on the engine: attach it to the next message (false when there is no room) */
  onAttach: (done: UploadedAttachment) => boolean;
  onInsert: (text: string) => void;
  onClose: () => void;
}) {
  const [servers, setServers] = useState<Loaded[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const list = await control.servers();
      const loaded = await Promise.all(
        list.map(async (s) => {
          try {
            const [resources, prompts] = await Promise.all([
              control.resources(s.id),
              control.prompts(s.id),
            ]);
            return { ...s, resources, prompts, error: "" };
          } catch (e) {
            return { ...s, resources: [], prompts: [], error: problem(e) };
          }
        }),
      );
      setServers(loaded);
    } catch (e) {
      setError(problem(e));
      setServers([]);
    }
  }, [control]);
  useEffect(() => {
    void load();
  }, [load]);
  async function attach(server: Loaded, r: ExternalResource) {
    setError(null);
    try {
      const done = await control.attachResource(server.id, r.uri);
      if (!onAttach(done)) setError("There is no room for another attachment on this message.");
    } catch (e) {
      setError(problem(e));
    }
  }
  return (
    <section
      aria-label="Tools from other apps"
      className="mb-2 grid gap-2 rounded-2xl border bg-accent/40 p-3 text-sm"
    >
      <p className="m-0 font-medium">From the servers you connected</p>
      {servers === null ? <p className="m-0 text-muted-foreground">Looking…</p> : null}
      {servers?.length === 0 ? (
        <p className="m-0 text-muted-foreground">
          No server is connected. Add one under Settings › Other apps › Tools from other apps.
        </p>
      ) : null}
      {servers?.map((s) => (
        <div key={s.id} className="grid gap-1">
          <p className="m-0 font-medium text-xs">{s.name}</p>
          {s.error ? <p className="m-0 text-destructive text-xs">{s.error}</p> : null}
          {s.resources.length ? (
            <ul className="m-0 grid list-none gap-1 p-0" aria-label={`Resources of ${s.name}`}>
              {s.resources.map((r) => (
                <li key={r.uri} className="flex flex-wrap items-center gap-2">
                  <span>{r.name}</span>
                  {r.description ? (
                    <span className="text-muted-foreground text-xs">{r.description}</span>
                  ) : null}
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => void attach(s, r)}
                  >
                    Attach
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
          {s.prompts.length ? (
            <ul className="m-0 grid list-none gap-1 p-0" aria-label={`Prompts of ${s.name}`}>
              {s.prompts.map((p) => (
                <PromptRow
                  key={p.name}
                  server={s}
                  prompt={p}
                  control={control}
                  onInsert={onInsert}
                  onError={setError}
                />
              ))}
            </ul>
          ) : null}
          {!s.resources.length && !s.prompts.length && !s.error ? (
            <p className="m-0 text-muted-foreground text-xs">Nothing to read or fill in here.</p>
          ) : null}
        </div>
      ))}
      {error ? <p className="m-0 text-destructive text-xs">{error}</p> : null}
      <div>
        <Button type="button" size="sm" variant="outline" onClick={onClose}>
          Close
        </Button>
      </div>
    </section>
  );
}

/** The panel inside the chat: a template goes into the box through the chat runtime. */
export function ComposerServersPanel(props: Omit<Parameters<typeof ServersPanel>[0], "onInsert">) {
  const aui = useAui();
  return <ServersPanel {...props} onInsert={(text) => aui.composer().setText(text)} />;
}
