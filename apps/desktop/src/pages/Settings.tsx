// SPDX-License-Identifier: AGPL-3.0-only
import {
  AgentPrograms,
  Button,
  Checkbox,
  ComputerCanDo,
  ConnectionsSettings,
  ExternalServers,
  Input,
  SearchSettings,
  Segmented,
  Textarea,
  YourKeys,
  useTheme,
} from "@wasifyai/ui";
import {
  Code,
  Cpu,
  KeyRound,
  LifeBuoy,
  type LucideIcon,
  PlugZap,
  Search,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { ComponentsPanel } from "../ComponentsPanel";
import {
  assistantApi,
  componentsApi,
  connectionsApi,
  discoveryApi,
  externalApi,
  hubApi,
  ownKeysApi,
} from "../api";
import { agentsApi } from "../choices/agents";
import { code } from "../code";
import { saveDiagnostics } from "../diagnostics";
import { engineRepair, engineRestart } from "../engine";
import { ImageEngineCard, LanguageEngineCard, UpdateBanner } from "../parts";
import {
  type SettingsGroupId,
  onSettingsGroup,
  showSettingsGroup,
  takeSettingsGroup,
} from "../settings-group";

/** "Saved." beside a setting that saves as it changes, or what went wrong. */
function SavedLine({ state }: { state: "idle" | "saving" | "saved" | string }) {
  return (
    <output aria-live="polite" className="text-sm">
      {state === "saving" ? (
        <span className="text-muted-foreground">Saving…</span>
      ) : state === "saved" ? (
        <span className="text-muted-foreground">Saved.</span>
      ) : state !== "idle" ? (
        <span className="text-destructive">{state}</span>
      ) : null}
    </output>
  );
}

/** One zip to send when something goes wrong: what is in it is said before it is made. */
function Diagnostics() {
  const [state, setState] = useState<"idle" | "saving" | string>("idle");
  async function run() {
    setState("saving");
    try {
      const saved = await saveDiagnostics();
      setState(saved ? `Saved ${saved.name}.` : "idle");
    } catch (e) {
      setState(e instanceof Error ? e.message : "The file could not be saved.");
    }
  }
  return (
    <div className="grid gap-3">
      <p className="m-0 text-muted-foreground text-sm">
        One zip file to send when something goes wrong: versions, the state of each part, your last
        50 actions (not what you asked) and the engine's logs. No pictures, sounds, documents,
        prompts, chats or keys.
      </p>
      <div className="flex items-center gap-3">
        <Button
          type="button"
          variant="outline"
          disabled={state === "saving"}
          onClick={() => void run()}
        >
          Save a report file
        </Button>
        <output aria-live="polite" className="text-sm">
          {state === "saving" ? (
            <span className="text-muted-foreground">Making the file…</span>
          ) : state.startsWith("Saved") ? (
            <span className="text-muted-foreground">{state}</span>
          ) : state !== "idle" ? (
            <span className="text-destructive">{state}</span>
          ) : null}
        </output>
      </div>
    </div>
  );
}

/** The light or dark look, or the system's. */
function ThemeSetting() {
  const { chosen, choose } = useTheme();
  return (
    <div className="grid gap-2">
      <p className="m-0 text-muted-foreground text-sm">
        Light, dark, or the same as this computer.
      </p>
      <Segmented
        label="Theme"
        value={chosen ?? "system"}
        onValueChange={(v) => choose(v === "light" || v === "dark" ? v : null)}
        options={[
          { value: "system", label: "Like the computer" },
          { value: "light", label: "Light" },
          { value: "dark", label: "Dark" },
        ]}
      />
    </div>
  );
}

/** The automatic look for models other tools left here (ADR-0063): a switch and extra folders, saved as they change. */
function FindingModels() {
  // null until the engine has said: a switch shown before then would save a guess
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [folders, setFolders] = useState("");
  const [state, setState] = useState<string>("idle");
  const foldersId = useId();
  const kept = useRef<string>(""); // the folders as last saved, so leaving the box unchanged saves nothing

  useEffect(() => {
    discoveryApi
      .state()
      .then((s) => {
        setEnabled(s.enabled);
        setFolders(s.folders.join("\n"));
        kept.current = s.folders.join("\n");
      })
      .catch(() => {});
  }, []);

  // one save at a time, in the order they were asked for: two quick clicks must not land the other way round
  const queue = useRef<Promise<void>>(Promise.resolve());
  function save(nextEnabled: boolean, nextFolders: string) {
    queue.current = queue.current.then(() => send(nextEnabled, nextFolders));
    return queue.current;
  }

  async function send(nextEnabled: boolean, nextFolders: string) {
    setState("saving");
    try {
      await discoveryApi.settings(
        nextEnabled,
        nextFolders
          .split("\n")
          .map((f) => f.trim())
          .filter(Boolean),
      );
      kept.current = nextFolders;
      setState("saved");
    } catch (e) {
      setState(e instanceof Error ? e.message : "That could not be saved.");
    }
  }

  if (enabled === null) return null;

  return (
    <div className="grid gap-3">
      <p className="m-0 text-muted-foreground text-sm">
        Lists the models that Ollama, LM Studio, ComfyUI and the Hugging Face cache keep on this
        computer in the Model hub. Nothing is copied or changed.
      </p>
      <Checkbox
        checked={enabled}
        onCheckedChange={(on) => {
          setEnabled(on);
          void save(on, folders);
        }}
        label="Look for models when the app starts"
      />
      <div className="grid gap-1 text-sm">
        <label htmlFor={foldersId}>More folders to look in (one per line)</label>
        <Textarea
          id={foldersId}
          className="min-h-20 font-mono"
          value={folders}
          onChange={(e) => setFolders(e.target.value)}
          onBlur={() => {
            if (folders !== kept.current) void save(enabled, folders);
          }}
          placeholder="/Volumes/Models"
        />
      </div>
      <SavedLine state={state} />
    </div>
  );
}

/** Whether the app may contact huggingface.co to list models (ADR-0064): off until the person agrees. */
function HubSwitch() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [state, setState] = useState<string>("idle");
  const queue = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => {
    hubApi
      .state()
      .then((s) => setEnabled(s.enabled))
      .catch(() => {});
  }, []);
  if (enabled === null) return null;
  return (
    <div className="grid gap-3">
      <p className="m-0 text-muted-foreground text-sm">
        Discover, in the Model hub, sends the words you search for and the models you open to
        huggingface.co, with no account. Off: nothing is sent.
      </p>
      <Checkbox
        checked={enabled}
        onCheckedChange={(next) => {
          setEnabled(next);
          setState("saving");
          // one at a time, in order, as with Finding models
          queue.current = queue.current.then(() =>
            hubApi
              .setEnabled(next)
              .then((r) => {
                setEnabled(r.enabled);
                setState("saved");
              })
              .catch((err) => setState(err instanceof Error ? err.message : "That did not work.")),
          );
        }}
        label="Browse models on Hugging Face"
      />
      <SavedLine state={state} />
    </div>
  );
}

/** The person's Hugging Face token (ADR-0092): typed once, kept in the keychain, never shown again. */
function HubToken() {
  const id = useId();
  const [state, setState] = useState<{ set: boolean; canSave: boolean } | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    hubApi
      .state()
      .then((s) => setState({ set: s.token_set === true, canSave: s.can_save_token !== false }))
      .catch(() => {});
  }, []);
  if (state === null) return null;
  async function run(action: () => Promise<{ token_set: boolean }>) {
    setBusy(true);
    setError(null);
    try {
      const r = await action();
      setState((s) => (s ? { ...s, set: r.token_set } : s));
      setValue("");
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "That could not be saved.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="grid gap-3">
      <label htmlFor={id} className="text-sm">
        Account token {state.set ? "(saved)" : "(not saved)"}
        <span className="block text-muted-foreground">
          Needed only for models whose authors ask you to sign in. Kept in the keychain and sent
          only to huggingface.co.
        </span>
      </label>
      {/* a secret is saved on its button, never as it is typed */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id={id}
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          disabled={!state.canSave}
          placeholder={state.set ? "Type a new token to replace it" : "Paste your token (hf_...)"}
          onChange={(e) => setValue(e.target.value)}
          className="min-w-0 flex-1"
        />
        <Button
          type="button"
          variant="outline"
          disabled={busy || !state.canSave || !value.trim()}
          onClick={() => void run(() => hubApi.setToken(value))}
        >
          Save token
        </Button>
        {state.set ? (
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => void run(() => hubApi.removeToken())}
          >
            Remove token
          </Button>
        ) : null}
      </div>
      {!state.canSave ? (
        <p className="text-muted-foreground text-xs">Tokens cannot be saved on this computer.</p>
      ) : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </div>
  );
}

/** One row of "What leaves this computer": what goes where, and the group where it is changed. */
function Leaves({
  title,
  line,
  to,
}: { title: string; line: string; to?: [SettingsGroupId, string] }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm">
      <span className="min-w-0 flex-1">
        {title}
        <span className="block text-muted-foreground">{line}</span>
      </span>
      {to ? (
        <Button
          type="button"
          variant="link"
          className="h-auto p-0"
          onClick={() => showSettingsGroup(to[0])}
        >
          {to[1]}
        </Button>
      ) : null}
    </li>
  );
}

/** What leaves this computer, in one place: each row names where it is changed. */
function WhatLeaves() {
  return (
    <ul className="m-0 list-none divide-y p-0">
      <Leaves
        title="Cloud models"
        line="What you make with a cloud model goes to its provider, on your key."
        to={["keys", "Cloud keys"]}
      />
      <Leaves
        title="Web search"
        line="Sends your question to the search service you choose, when you allow it below."
      />
      <Leaves
        title="Browsing models"
        line="Sends the words you search for to huggingface.co, while it is on."
        to={["computer", "On this computer"]}
      />
      <Leaves
        title="Getting a model"
        line="Downloads it from the place its row names. Nothing is uploaded."
      />
      <Leaves
        title="Other apps"
        line="Reached only after you add them."
        to={["apps", "Other apps"]}
      />
    </ul>
  );
}

type Item = {
  id: string;
  title: string;
  words: string;
  body: ReactNode;
  /** the shared screen draws its own cards */
  own?: boolean;
};
type Group = {
  id: SettingsGroupId;
  title: string;
  /** one line under the title: what the group is for */
  line: string;
  icon: LucideIcon;
  items: Item[];
};

const agents = agentsApi({ code, parts: componentsApi });

const GROUPS: Group[] = [
  {
    id: "general",
    title: "General",
    line: "How the app looks and stays up to date.",
    icon: Settings2,
    items: [
      { id: "theme", title: "Look", words: "theme light dark look colour", body: <ThemeSetting /> },
      {
        id: "updates",
        title: "Updates",
        words: "version new release",
        body: (
          <div className="grid gap-2">
            <UpdateBanner />
            <p className="m-0 text-muted-foreground text-sm">
              The app looks for a newer version when it starts, once an update feed is set up.
            </p>
          </div>
        ),
      },
    ],
  },
  {
    id: "keys",
    title: "Cloud keys",
    line: "Use cloud models with your own provider keys.",
    icon: KeyRound,
    items: [
      {
        id: "own-keys",
        title: "Cloud keys",
        words:
          "your keys api key provider anthropic claude haiku openai gpt gemini google deepseek z.ai glm openrouter media runware wavespeed fal hosted cloud own key",
        body: <YourKeys api={ownKeysApi} />,
        own: true,
      },
    ],
  },
  {
    id: "computer",
    title: "On this computer",
    line: "The parts and models that run here, with no cloud.",
    icon: Cpu,
    items: [
      {
        id: "can-do",
        title: "What this computer can do",
        words: "memory chip what can run",
        body: <ComputerCanDo />,
        own: true,
      },
      {
        id: "images",
        title: "Picture engine",
        words: "engine comfyui pictures image generation",
        body: <ImageEngineCard />,
      },
      {
        id: "language",
        title: "Chat and writing engine",
        words: "engine llama chat language models",
        body: <LanguageEngineCard />,
      },
      {
        id: "parts",
        title: "Optional parts",
        words:
          "components install set up repair remove speech lip sync 3d motion graphics trainer reader",
        body: <ComponentsPanel />,
      },
      {
        id: "finding",
        title: "Models you already have",
        words: "finding folders ollama lm studio look scan",
        body: <FindingModels />,
      },
      {
        id: "hub",
        title: "Hugging Face",
        words: "browsing discover hugging face token gated keychain account",
        body: (
          <div className="grid gap-4">
            <HubSwitch />
            <HubToken />
          </div>
        ),
      },
    ],
  },
  {
    id: "code",
    title: "Code",
    line: "Run coding sessions on your own Claude Code or Codex, on your plan, with no key.",
    icon: Code,
    items: [
      {
        // the person's own agent programs (ADR-0107, stage H2): their sign-in, and the part that holds them
        id: "agent-programs",
        title: "Your agent programs",
        words: "claude code codex agent program plan sign in subscription harness",
        body: <AgentPrograms api={agents} />,
      },
    ],
  },
  {
    id: "privacy",
    title: "Privacy",
    line: "What you make, your files and your chats stay on this computer. This is everything that can leave it, and each one is your choice.",
    icon: ShieldCheck,
    items: [
      {
        id: "leaves",
        title: "What leaves this computer",
        words: "privacy data sent network sharing",
        body: <WhatLeaves />,
      },
      {
        id: "search",
        title: "Web search",
        words: "searching duckduckgo tavily web search consent",
        body: (
          <div className="rounded-xl border bg-card p-4 empty:hidden">
            <SearchSettings assistant={assistantApi} />
          </div>
        ),
        own: true,
      },
    ],
  },
  {
    id: "apps",
    title: "Other apps",
    line: "Connect Wasify AI with the other apps you use. Nothing is connected until you add it here.",
    icon: PlugZap,
    items: [
      {
        id: "connections",
        title: "Apps that can use Wasify AI",
        words: "connections mcp claude code codex opencode cursor other apps launcher secret port",
        body: <ConnectionsSettings api={connectionsApi} />,
        own: true,
      },
      {
        id: "tools",
        title: "Tools Wasify AI can use",
        words: "tools from other apps mcp servers external github import",
        body: <ExternalServers api={externalApi} />,
        own: true,
      },
    ],
  },
  {
    id: "help",
    title: "Help and repair",
    line: "For when something seems stuck or broken.",
    icon: LifeBuoy,
    items: [
      {
        id: "engine",
        title: "Fix a problem",
        words: "advanced engine restart repair process stuck",
        body: (
          <ul className="m-0 list-none divide-y p-0">
            <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm">
              <span className="min-w-0 flex-1">
                Restart the engine
                <span className="block text-muted-foreground">
                  Try this first. The part that makes things starts again; nothing you made is lost.
                </span>
              </span>
              <Button type="button" variant="outline" onClick={() => void engineRestart()}>
                Restart
              </Button>
            </li>
            <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm">
              <span className="min-w-0 flex-1">
                Repair the installation
                <span className="block text-muted-foreground">
                  Rebuilds the engine's files, if restarting did not help. It takes longer.
                </span>
              </span>
              <Button type="button" variant="outline" onClick={() => void engineRepair()}>
                Repair
              </Button>
            </li>
          </ul>
        ),
      },
      {
        id: "diagnostics",
        title: "Report a problem",
        words: "diagnostics logs support problem report zip",
        body: <Diagnostics />,
      },
    ],
  },
];

const matches = (q: string, ...texts: string[]) =>
  q === "" || texts.some((t) => t.toLowerCase().includes(q));

/** A setting's card: a short title, then the setting. */
function SettingCard({ item, hidden }: { item: Item; hidden: boolean }) {
  if (item.own) {
    return <div hidden={hidden}>{item.body}</div>;
  }
  return (
    <section
      hidden={hidden}
      aria-label={item.title}
      className="grid gap-3 rounded-xl border bg-card p-4"
    >
      <h3 className="m-0 font-medium text-muted-foreground text-sm">{item.title}</h3>
      {item.body}
    </section>
  );
}

/**
 * Settings (ADR-0093 U11; the redesign approved on 2026-11-15): six groups (General, Cloud keys, On this computer,
 * Privacy, Other apps, Help and repair) listed on the left, one shown at a time with one line on what it is for; each
 * setting is a card with a short title and one line of help, and saves as it changes. A search shows every matching
 * setting across the groups. Every group stays mounted, hidden when not shown, so a setting keeps what it read and
 * what was typed in it.
 */
export function SettingsPage() {
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState<SettingsGroupId>(() => takeSettingsGroup() ?? "general");
  const top = useRef<HTMLDivElement>(null);
  // a group is shown from its top, from the list or from another screen
  const open = useCallback((id: SettingsGroupId) => {
    setQuery("");
    setGroup(id);
    top.current?.scrollIntoView({ block: "start" });
  }, []);
  useEffect(() => onSettingsGroup(open), [open]);
  const q = query.trim().toLowerCase();
  const hit = (g: Group, i: Item) => matches(q, g.title, i.title, i.words);
  const shown = (g: Group) => (q === "" ? g.id === group : g.items.some((i) => hit(g, i)));
  const any = GROUPS.some(shown);
  return (
    <div className="mx-auto grid w-full max-w-5xl gap-8 px-8 pt-10 pb-12 md:grid-cols-[12rem_minmax(0,1fr)]">
      <aside className="md:sticky md:top-6 md:self-start">
        <div className="grid gap-3">
          <div className="relative">
            <Search
              className="pointer-events-none absolute start-2.5 top-2.5 size-4 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              type="search"
              aria-label="Search settings"
              placeholder="Search settings"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="ps-8"
            />
          </div>
          <nav aria-label="Settings groups">
            <ul className="m-0 grid list-none gap-0.5 p-0">
              {GROUPS.map((g) => {
                const current = q === "" && g.id === group;
                const Icon = g.icon;
                return (
                  <li key={g.id}>
                    <button
                      type="button"
                      aria-current={current ? "page" : undefined}
                      className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-start text-sm hover:bg-accent ${current ? "bg-accent font-medium" : "text-muted-foreground"}`}
                      onClick={() => open(g.id)}
                    >
                      <Icon aria-hidden="true" className="size-4 shrink-0" />
                      {g.title}
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
        </div>
      </aside>

      <div ref={top} className="grid min-w-0 scroll-mt-6 content-start gap-8">
        {!any ? (
          <p className="m-0 text-muted-foreground">No setting matches “{query.trim()}”.</p>
        ) : null}
        {GROUPS.map((g) => (
          <section
            key={g.id}
            hidden={!shown(g)}
            id={`settings-${g.id}`}
            aria-labelledby={`settings-${g.id}-title`}
            className="grid content-start gap-4"
          >
            <div className="grid gap-1">
              {q === "" ? (
                <h1 id={`settings-${g.id}-title`} className="m-0 font-semibold text-2xl">
                  {g.title}
                </h1>
              ) : (
                <h2 id={`settings-${g.id}-title`} className="m-0 font-semibold text-lg">
                  {g.title}
                </h2>
              )}
              {q === "" ? <p className="m-0 text-muted-foreground text-sm">{g.line}</p> : null}
            </div>
            {g.items.map((i) => (
              <SettingCard key={i.id} item={i} hidden={!hit(g, i)} />
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
