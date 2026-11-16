"use client";
// Extensions (ADR-0104; mockups `extensions`, `extension-detail`, `extension-add`): the skills that teach the
// agent a way of working. A short list chosen for Wasify AI, a few of the public OpenHands catalogue, and what
// the person added from a folder. Each is on or off for one project. A skill's text is shown before it is
// switched on: it comes from outside, and it cannot widen what the agent may do. A plugin (stage X3; mockup
// `extension-approve`) can bring hooks and tool connections too: it stays off until the person has seen what
// it brings and approved it, once.
import type {
  CodeApi,
  CodeBrings,
  CodeExtension,
  CodeExtensionDetail,
  CodeFolderLook,
  CodeWorkspace,
} from "@wasifyai/client";
import { ChevronRight, FolderOpen, Plug, Puzzle, Search, Sparkles, Trash2 } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ConfirmDialog, Modal } from "../components/dialog";
import { EmptyState } from "../components/empty-state";
import { Input } from "../components/input";
import { Notice } from "../components/notice";
import { Spinner } from "../components/spinner";

const say = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/** Where an extension comes from, in words. */
export const FROM: Record<CodeExtension["source"], string> = {
  own: "Wasify AI",
  catalogue: "OpenHands catalogue",
  added: "Your folder",
};

/** What a plugin brings, counted in words: "1 skill, 1 hook and 1 tool connection". */
export function bringsWords(b: CodeBrings): string {
  const n = (count: number, one: string) =>
    count ? `${count} ${one}${count === 1 ? "" : "s"}` : "";
  const parts = [
    n(b.skills.length, "skill"),
    n(b.hooks.length, "hook"),
    n(b.connections.length, "tool connection"),
  ].filter(Boolean);
  return parts.length > 1
    ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`
    : (parts[0] ?? "nothing");
}

const bringsOf = (x: { brings?: CodeBrings | "text" }): CodeBrings | null =>
  x.brings && x.brings !== "text" ? x.brings : null;

type Filter = "all" | "on" | "own" | "catalogue" | "added";
const FILTERS: [Filter, string][] = [
  ["all", "All"],
  ["on", "On"],
  ["own", "Wasify AI"],
  ["catalogue", "Public"],
  ["added", "Yours"],
];

/** A switch: on or off for one project. */
function Switch({
  on,
  label,
  disabled,
  onChange,
}: {
  on: boolean;
  label: string;
  disabled?: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={cn(
        "relative h-6 w-10 shrink-0 rounded-full border outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
        on ? "border-primary bg-primary" : "bg-muted",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "absolute top-0.5 size-4.5 rounded-full bg-background shadow transition-[inset-inline-start]",
          on ? "start-[1.125rem]" : "start-0.5",
        )}
      />
    </button>
  );
}

export function Extensions({
  api,
  pickFolder,
  onOpenProjects,
}: {
  api: CodeApi;
  /** The computer's own folder window; the chosen folder's whole path, or null when it was closed. */
  pickFolder: () => Promise<string | null>;
  /** Where a project is opened (Code, Projects). */
  onOpenProjects: () => void;
}) {
  const [projects, setProjects] = useState<CodeWorkspace[] | null>(null);
  const [project, setProject] = useState("");
  const [items, setItems] = useState<CodeExtension[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState<CodeFolderLook | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const projectId = useId();
  const searchId = useId();

  useEffect(() => {
    let gone = false;
    api
      .workspaces()
      .then((found) => {
        if (gone) return;
        setProjects(found);
        setProject((p) => p || found[0]?.id || "");
      })
      .catch((e) => {
        if (!gone) setProblem(say(e, "The projects could not be read."));
      });
    return () => {
      gone = true;
    };
  }, [api]);

  const read = useCallback(async () => {
    try {
      setItems(await api.extensions(project));
      setProblem(null);
    } catch (e) {
      setProblem(say(e, "The extensions could not be read."));
    }
  }, [api, project]);
  useEffect(() => {
    if (projects !== null) void read();
  }, [projects, read]);

  const flip = async (item: CodeExtension, on: boolean) => {
    if (!project) return;
    setBusy(item.id);
    try {
      await api.switchExtension(item.id, project, on);
      setItems((all) => (all ?? []).map((x) => (x.id === item.id ? { ...x, on } : x)));
      setProblem(null);
    } catch (e) {
      setProblem(say(e, "That could not be changed."));
    }
    setBusy(null);
  };
  const choose = async () => {
    const folder = await pickFolder();
    if (!folder) return;
    try {
      setAdding(await api.lookAtFolder(folder));
      setProblem(null);
    } catch (e) {
      setProblem(say(e, "That folder could not be read."));
    }
  };

  const current = projects?.find((p) => p.id === project);
  const q = query.trim().toLowerCase();
  const shown = (items ?? []).filter(
    (x) =>
      (filter === "all" || (filter === "on" ? x.on === true : x.source === filter)) &&
      (!q ||
        `${x.title} ${x.name} ${x.description} ${x.triggers.join(" ")}`.toLowerCase().includes(q)),
  );

  return (
    <div className="mx-auto grid w-[min(100%-2rem,56rem)] gap-5 pt-8 pb-16">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid gap-1.5">
          <h1 className="m-0 text-2xl font-semibold">Extensions</h1>
          <p className="m-0 max-w-[60ch] text-muted-foreground">
            Skills and plugins that teach the agent a way of working. Each is switched on or off for
            one project.
          </p>
          <p className="m-0 max-w-[60ch] text-sm text-muted-foreground">
            For Wasify AI's own agent only. Sessions on Claude Code or Codex use the extensions set
            up in those programs, not these.
          </p>
        </div>
        <Button variant="outline" onClick={() => void choose()}>
          <FolderOpen /> Add from a folder
        </Button>
      </div>
      {problem ? (
        <Notice tone="error" title="That did not work">
          {problem}
        </Notice>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        {projects?.length ? (
          <div className="flex items-center gap-2 text-sm">
            <label htmlFor={projectId} className="text-muted-foreground">
              For
            </label>
            <select
              id={projectId}
              value={project}
              onChange={(e) => setProject(e.target.value)}
              className="h-9 rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="relative min-w-48 flex-1">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute start-2.5 top-2.5 size-4 text-muted-foreground"
          />
          <label htmlFor={searchId} className="sr-only">
            Search extensions
          </label>
          <Input
            id={searchId}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search extensions"
            className="ps-8"
          />
        </div>
        <fieldset className="m-0 flex flex-wrap gap-1 border-0 p-0" aria-label="Which to show">
          {FILTERS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
              className="rounded-full border px-2.5 py-1 text-xs outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-pressed:bg-accent aria-pressed:font-semibold"
            >
              {label}
            </button>
          ))}
        </fieldset>
      </div>
      {projects !== null && projects.length === 0 ? (
        <Notice
          tone="info"
          title="Open a project first"
          actions={
            <Button size="sm" variant="outline" onClick={onOpenProjects}>
              Open Projects
            </Button>
          }
        >
          An extension is switched on for a project. You can read what each one says before you have
          one.
        </Notice>
      ) : null}
      {items === null ? (
        <div className="grid place-items-center py-10">
          <Spinner />
        </div>
      ) : shown.length === 0 ? (
        <EmptyState
          icon={Puzzle}
          title={items.length ? "Nothing matches" : "No extensions here yet"}
          text={
            items.length
              ? "Try another word, or show all."
              : "The coding engine holds the public ones. Set it up in Settings, under Optional parts, or add one from a folder."
          }
        />
      ) : (
        <ul className="m-0 grid list-none gap-2 p-0">
          {shown.map((x) => (
            <li
              key={x.id}
              className="flex items-center gap-3 rounded-lg border bg-surface px-3.5 py-3"
            >
              {x.kind === "plugin" ? (
                <Plug aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
              ) : (
                <Sparkles aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
              )}
              <div className="grid min-w-0 flex-1 gap-0.5">
                <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
                  <span className="font-semibold">{x.title}</span>
                  <span className="rounded border px-1.5 text-xs text-muted-foreground">
                    {x.kind === "plugin" ? "Plugin" : "Skill"}
                  </span>
                  <span className="text-xs text-muted-foreground">{FROM[x.source]}</span>
                </p>
                <p className="m-0 line-clamp-2 text-sm text-muted-foreground">
                  {x.description}
                  {bringsOf(x) ? ` Brings ${bringsWords(bringsOf(x) as CodeBrings)}.` : ""}
                </p>
              </div>
              {x.needs_approval ? (
                <Button size="sm" variant="outline" onClick={() => setOpen(x.id)}>
                  Look and switch on
                </Button>
              ) : current ? (
                <Switch
                  on={x.on === true}
                  disabled={busy === x.id}
                  label={`${x.title}: ${x.on ? "on" : "off"} for ${current.name}`}
                  onChange={(on) => void flip(x, on)}
                />
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setOpen(x.id)}
                aria-label={`Details of ${x.title}`}
              >
                Details <ChevronRight />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <p className="m-0 text-xs text-muted-foreground">
        A short list chosen for Wasify AI. Everything here is already on this computer; nothing is
        fetched from the internet while you work. A change holds from a session’s next message.
      </p>
      {open ? (
        <Detail api={api} id={open} onClose={() => setOpen(null)} onChanged={() => void read()} />
      ) : null}
      {adding ? (
        <Add
          api={api}
          found={adding}
          project={current}
          onChooseAnother={() => void choose()}
          onClose={() => setAdding(null)}
          onAdded={() => {
            setAdding(null);
            void read();
          }}
        />
      ) : null}
    </div>
  );
}

/** What a plugin brings, listed: this is what the person approves. */
function Brings({ brings }: { brings: CodeBrings }) {
  return (
    <div className="grid gap-2">
      <h3 className="m-0 text-sm font-semibold">What it brings</h3>
      <ul className="m-0 grid list-none gap-1.5 p-0 text-sm">
        {brings.skills.map((s) => (
          <li key={`s-${s.name}`} className="rounded-md border px-3 py-2">
            <strong className="font-semibold">A skill: {s.name}.</strong>{" "}
            <span className="text-muted-foreground">{s.description} Text only.</span>
          </li>
        ))}
        {brings.hooks.map((h) => (
          <li key={`h-${h.when}-${h.command}`} className="grid gap-1 rounded-md border px-3 py-2">
            <span>
              <strong className="font-semibold">A hook, {h.when}</strong>
              {h.on && h.on !== "*" ? ` (for ${h.on})` : ""}.{" "}
              <span className="text-muted-foreground">
                The coding engine runs this command by itself, inside its sandbox, and stops it
                after one second.
              </span>
            </span>
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs break-all">{h.command}</code>
          </li>
        ))}
        {brings.connections.map((c) => (
          <li key={`c-${c.name}`} className="rounded-md border px-3 py-2">
            <strong className="font-semibold">A tool connection: {c.name}</strong>
            {c.to ? (
              <>
                {" "}
                to <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{c.to}</code>
              </>
            ) : null}
            .{" "}
            <span className="text-muted-foreground">
              Named here so that you know of it. Wasify AI does not connect it in this version.
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A skill's text, with the note that it comes from outside. */
function SkillText({
  text,
  lines,
  own,
  plugin,
}: {
  text: string;
  lines: number;
  own: boolean;
  plugin?: boolean;
}) {
  if (plugin)
    return (
      <div className="grid gap-2">
        <h3 className="m-0 text-sm font-semibold">What the plugin says about itself</h3>
        <pre
          // biome-ignore lint/a11y/noNoninteractiveTabindex: a long text must be scrollable by keyboard
          tabIndex={0}
          aria-label="The plugin's own description file"
          className="m-0 max-h-48 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {text}
        </pre>
        <p className="m-0 text-xs text-muted-foreground">
          .plugin/plugin.json · {lines} line{lines === 1 ? "" : "s"} · shown as plain text
        </p>
      </div>
    );
  return (
    <div className="grid gap-2">
      <h3 className="m-0 text-sm font-semibold">The text it gives the agent</h3>
      <Notice
        tone="warn"
        title={own ? "Read it before you switch it on" : "This text was not written by Wasify AI"}
      >
        {own ? "" : "Read it before you switch it on. "}It can steer how the agent works. It cannot
        widen what the agent may do: the folder, the internet and your approvals stay as they are.
      </Notice>
      <pre
        // biome-ignore lint/a11y/noNoninteractiveTabindex: a long text must be scrollable by keyboard
        tabIndex={0}
        aria-label="The skill's text"
        className="m-0 max-h-80 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {text}
      </pre>
      <p className="m-0 text-xs text-muted-foreground">
        SKILL.md · {lines} line{lines === 1 ? "" : "s"} · shown as plain text
      </p>
    </div>
  );
}

function when(triggers: string[]): string {
  if (!triggers.length) {
    return "When the agent judges that it fits what you asked: it sees the skill's name and what it is for.";
  }
  const shown = triggers.slice(0, 6).map((t) => `“${t}”`);
  return `When your message has one of its words, for example ${shown.join(", ")}.`;
}

function Detail({
  api,
  id,
  onClose,
  onChanged,
}: {
  api: CodeApi;
  id: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<CodeExtensionDetail | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  useEffect(() => {
    let gone = false;
    api
      .extension(id)
      .then((d) => {
        if (!gone) setDetail(d);
      })
      .catch((e) => {
        if (!gone) setProblem(say(e, "That extension could not be read."));
      });
    return () => {
      gone = true;
    };
  }, [api, id]);
  const flip = async (workspaceId: string, on: boolean) => {
    try {
      await api.switchExtension(id, workspaceId, on);
      setDetail((d) =>
        d ? { ...d, where: d.where.map((w) => (w.id === workspaceId ? { ...w, on } : w)) } : d,
      );
      setProblem(null);
      onChanged();
    } catch (e) {
      setProblem(say(e, "That could not be changed."));
    }
  };
  const approve = async () => {
    try {
      const d = await api.approveExtension(id);
      setDetail((was) => (was ? { ...was, ...d, where: was.where } : was));
      setProblem(null);
      onChanged();
    } catch (e) {
      setProblem(say(e, "That could not be approved."));
    }
  };
  const remove = async () => {
    try {
      await api.removeExtension(id);
      onChanged();
      onClose();
    } catch (e) {
      setProblem(say(e, "That could not be removed."));
      setRemoving(false);
    }
  };
  return (
    <Modal label={detail ? detail.title : "An extension"} onClose={onClose} wide>
      {detail ? (
        <>
          <p className="m-0 text-sm">{detail.description}</p>
          <p className="m-0 text-xs text-muted-foreground">
            A {detail.kind === "plugin" ? "plugin" : "skill"} · from {FROM[detail.source]}
            {detail.licence ? ` · licence: ${detail.licence}` : ""}
            {detail.files > 1 ? ` · ${detail.files} files` : ""} · already on this computer
          </p>
          {detail.needs ? (
            <p className="m-0 text-sm text-muted-foreground">It says it needs: {detail.needs}</p>
          ) : null}
          {detail.kind === "plugin" ? null : (
            <div className="grid gap-1">
              <h3 className="m-0 text-sm font-semibold">When the agent uses it</h3>
              <p className="m-0 text-sm text-muted-foreground">{when(detail.triggers)}</p>
            </div>
          )}
          {bringsOf(detail) ? <Brings brings={bringsOf(detail) as CodeBrings} /> : null}
          {detail.needs_approval ? (
            <Notice
              tone="warn"
              title="This plugin brings more than text"
              actions={
                <Button size="sm" onClick={() => void approve()}>
                  Approve what it brings
                </Button>
              }
            >
              It was not written by Wasify AI. Read the list above. It stays off until you approve
              it; you approve it once, and then switch it on for a project. A hook runs inside the
              same closed sandbox as the agent: it cannot reach the internet or your other folders.
            </Notice>
          ) : detail.kind === "plugin" && detail.approved ? (
            <p className="m-0 text-xs text-muted-foreground">You approved what it brings.</p>
          ) : null}
          <SkillText
            text={detail.text}
            lines={detail.lines}
            own={detail.source === "own"}
            plugin={detail.kind === "plugin"}
          />
          <div className="grid gap-2">
            <h3 className="m-0 text-sm font-semibold">Where it is on</h3>
            {detail.where.length ? (
              <ul className="m-0 grid list-none gap-1.5 p-0">
                {detail.where.map((w) => (
                  <li
                    key={w.id}
                    className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"
                  >
                    <span className="min-w-0 truncate">{w.name}</span>
                    <Switch
                      on={w.on}
                      disabled={detail.needs_approval}
                      label={`${detail.title}: ${w.on ? "on" : "off"} for ${w.name}`}
                      onChange={(on) => void flip(w.id, on)}
                    />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 text-sm text-muted-foreground">
                You have no project yet. Open one in Code, Projects.
              </p>
            )}
          </div>
        </>
      ) : problem ? null : (
        <Spinner className="size-4" />
      )}
      {problem ? (
        <p role="alert" className="m-0 text-sm text-destructive">
          {problem}
        </p>
      ) : null}
      <div className="flex justify-between gap-2">
        {detail?.source === "added" ? (
          <Button variant="ghost" onClick={() => setRemoving(true)}>
            <Trash2 /> Remove
          </Button>
        ) : (
          <span />
        )}
        <Button onClick={onClose}>Done</Button>
      </div>
      {removing && detail ? (
        <ConfirmDialog
          title={`Remove ${detail.title}?`}
          message="Wasify AI’s copy is removed and it is switched off everywhere. Your own folder is not touched."
          confirmLabel="Remove"
          destructive
          onConfirm={() => void remove()}
          onCancel={() => setRemoving(false)}
        />
      ) : null}
    </Modal>
  );
}

function Add({
  api,
  found,
  project,
  onChooseAnother,
  onClose,
  onAdded,
}: {
  api: CodeApi;
  found: CodeFolderLook;
  project: CodeWorkspace | undefined;
  onChooseAnother: () => void;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [on, setOn] = useState(Boolean(project));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const add = async () => {
    setBusy(true);
    try {
      const here = on && project && !found.needs_approval ? project.id : "";
      await api.addExtension(found.folder, here);
      onAdded();
    } catch (e) {
      setProblem(say(e, "It could not be added."));
      setBusy(false);
    }
  };
  const kb = found.bytes < 1024 ? `${found.bytes} bytes` : `${(found.bytes / 1024).toFixed(1)} KB`;
  const plugin = bringsOf(found);
  return (
    <Modal label="Add an extension from a folder" onClose={onClose} wide>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <code className="min-w-0 truncate rounded bg-muted px-1.5 py-0.5 text-xs">
          {found.folder}
        </code>
        <Button size="sm" variant="ghost" onClick={onChooseAnother}>
          Choose another
        </Button>
      </div>
      {plugin ? (
        <p className="m-0 text-sm">
          <strong className="font-semibold">Found a plugin: “{found.title}”.</strong> It brings{" "}
          {bringsWords(plugin)}.
        </p>
      ) : (
        <p className="m-0 text-sm">
          <strong className="font-semibold">Found a skill: “{found.title}”.</strong> SKILL.md, {kb}.
          It brings text only: no hook and no tool connection.
        </p>
      )}
      <p className="m-0 text-sm text-muted-foreground">{found.description}</p>
      {plugin ? <Brings brings={plugin} /> : null}
      {found.needs_approval ? (
        <Notice tone="warn" title="It stays off until you approve it">
          Adding copies it in and nothing more. Open its details afterwards to approve what it
          brings and switch it on.
        </Notice>
      ) : null}
      <SkillText text={found.text} lines={found.lines} own={false} plugin={Boolean(plugin)} />
      {project && !found.needs_approval ? (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} />
          Switch it on for {project.name}
        </label>
      ) : null}
      <p className="m-0 text-xs text-muted-foreground">
        It is copied into Wasify AI; your folder is not changed. A folder is an extension when it
        has a SKILL.md or a .plugin/plugin.json.
      </p>
      {problem ? (
        <p role="alert" className="m-0 text-sm text-destructive">
          {problem}
        </p>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={() => void add()} disabled={busy}>
          {busy ? <Spinner className="size-3.5" /> : null} Add the {plugin ? "plugin" : "skill"}
        </Button>
      </div>
    </Modal>
  );
}
