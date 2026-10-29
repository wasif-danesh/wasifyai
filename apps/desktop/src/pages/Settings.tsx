// SPDX-License-Identifier: AGPL-3.0-only
import {
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
import { Search } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { ComponentsPanel } from "../ComponentsPanel";
import {
  assistantApi,
  connectionsApi,
  discoveryApi,
  externalApi,
  hubApi,
  ownKeysApi,
} from "../api";
import { saveDiagnostics } from "../diagnostics";
import { engineRepair, engineRestart } from "../engine";
import { ImageEngineCard, LanguageEngineCard, UpdateBanner } from "../parts";

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
        One zip file to send when something goes wrong: the app's and the computer's versions, the
        state of each optional part, your last 50 actions (which ones and how they ended, not what
        you asked) and the end of the engine's logs. No pictures, sounds, documents, prompts or
        chats; keys and tokens are hidden.
      </p>
      <div className="flex items-center gap-3">
        <Button
          type="button"
          variant="outline"
          disabled={state === "saving"}
          onClick={() => void run()}
        >
          Save diagnostics
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
        How the app looks. "Like the computer" follows the system's light or dark setting.
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
        When the app starts it looks in the folders where tools such as Ollama, LM Studio, ComfyUI
        and the Hugging Face cache keep models, and lists what it finds in the Model hub. It reads
        only the start of each file, never copies or changes anything, and the list stays on this
        computer.
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
        Discover (in the Model hub) asks huggingface.co for lists of open models. It sends the words
        you search for and the names of the models you open, with no account. Nothing is requested
        while this is off.
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
        label="Let the app contact Hugging Face to browse models"
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
      <p className="m-0 text-muted-foreground text-sm">
        Some models on Hugging Face are gated: their authors ask you to accept a licence and sign in
        before a download. Paste a token from your Hugging Face account to fetch them. It is kept in
        this computer's keychain, sent only to huggingface.co, and never shown again.
      </p>
      <label htmlFor={id} className="text-sm">
        Token {state.set ? "(saved)" : "(not saved yet)"}
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

/** What leaves this computer, in one place: each item names the setting that sends it. */
function WhatLeaves() {
  return (
    <ul className="m-0 grid list-disc gap-1.5 ps-5 text-muted-foreground text-sm">
      <li>
        What you make, your files and your chats stay on this computer. Models run here, not on a
        service, unless you give a product your own key.
      </li>
      <li>
        Searching the web (below, when you allow it) sends your question to the search service you
        choose.
      </li>
      <li>
        Browsing models (under Models) sends the words you search for to huggingface.co, while it is
        on. A Hugging Face token is sent only there.
      </li>
      <li>Getting a model downloads it from the place its row names; nothing is uploaded.</li>
      <li>Other apps (connections and tools) are reached only once you add them.</li>
      <li>
        A product you set to run with your own key (Your keys) sends what you make with it to that
        provider.
      </li>
    </ul>
  );
}

type Item = {
  id: string;
  title: string;
  words: string;
  body: ReactNode;
  /** the shared section brings its own heading */
  own?: boolean;
};
type Group = { id: string; title: string; items: Item[] };

const GROUPS: Group[] = [
  {
    id: "general",
    title: "General",
    items: [
      { id: "theme", title: "Theme", words: "light dark look colour", body: <ThemeSetting /> },
      {
        id: "updates",
        title: "Updates",
        words: "version new release",
        body: (
          <div className="grid gap-2">
            <UpdateBanner />
            <p className="m-0 text-muted-foreground text-sm">
              The app checks for a newer version when it starts, once an update feed is set up.
            </p>
          </div>
        ),
      },
    ],
  },
  {
    id: "models",
    title: "Models",
    items: [
      {
        id: "images",
        title: "Image generation",
        words: "engine comfyui pictures",
        body: <ImageEngineCard />,
      },
      {
        id: "language",
        title: "Language models",
        words: "engine llama chat",
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
        title: "Finding models",
        words: "folders ollama lm studio look scan",
        body: <FindingModels />,
      },
      {
        id: "browsing",
        title: "Browsing models",
        words: "hugging face discover",
        body: <HubSwitch />,
      },
      {
        id: "token",
        title: "Hugging Face token",
        words: "gated keychain account",
        body: <HubToken />,
      },
    ],
  },
  {
    id: "keys",
    title: "Your keys",
    items: [
      {
        id: "own-keys",
        title: "Your keys",
        words: "api key provider openrouter openai anthropic gemini groq fal hosted cloud own key",
        body: <YourKeys api={ownKeysApi} />,
        own: true,
      },
    ],
  },
  {
    id: "privacy",
    title: "Privacy and sharing",
    items: [
      {
        id: "leaves",
        title: "What leaves this computer",
        words: "privacy data sent network",
        body: <WhatLeaves />,
      },
      {
        id: "search",
        title: "Searching the web",
        words: "duckduckgo tavily web search consent",
        body: <SearchSettings assistant={assistantApi} />,
        own: true,
      },
    ],
  },
  {
    id: "apps",
    title: "Other apps",
    items: [
      {
        id: "connections",
        title: "Connections",
        words: "mcp claude cursor other apps",
        body: <ConnectionsSettings api={connectionsApi} />,
        own: true,
      },
      {
        id: "tools",
        title: "Tools from other apps",
        words: "mcp servers external",
        body: <ExternalServers api={externalApi} />,
        own: true,
      },
    ],
  },
  {
    id: "advanced",
    title: "Advanced",
    items: [
      {
        id: "engine",
        title: "The engine",
        words: "restart repair process stuck",
        body: (
          <div className="grid gap-3">
            <p className="m-0 text-muted-foreground text-sm">
              The part of the app that makes things runs as its own process on this computer.
              Restart it if something seems stuck; repair rebuilds its environment.
            </p>
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => void engineRestart()}>
                Restart the engine
              </Button>
              <Button type="button" variant="outline" onClick={() => void engineRepair()}>
                Repair the installation
              </Button>
            </div>
          </div>
        ),
      },
      {
        id: "diagnostics",
        title: "Diagnostics",
        words: "diagnostics logs support problem report zip",
        body: <Diagnostics />,
      },
    ],
  },
];

const matches = (q: string, ...texts: string[]) =>
  q === "" || texts.some((t) => t.toLowerCase().includes(q));

/**
 * Settings (ADR-0093 U11): what this computer can do at the top, then five groups (General, Models, Privacy and
 * sharing, Other apps, Advanced) with a list of them on the left and a search; each setting saves as it changes.
 */
export function SettingsPage() {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  // a setting that does not match is hidden, not removed: it keeps what it read and what was typed in it
  const hit = (g: Group, i: Item) => matches(q, g.title, i.title, i.words);
  const shown = GROUPS.filter((g) => g.items.some((i) => hit(g, i)));
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
              {shown.map((g) => (
                <li key={g.id}>
                  <button
                    type="button"
                    className="w-full rounded-md px-2.5 py-1.5 text-start text-sm hover:bg-accent"
                    onClick={() =>
                      document
                        .getElementById(`settings-${g.id}`)
                        ?.scrollIntoView({ block: "start" })
                    }
                  >
                    {g.title}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </aside>

      <div className="grid min-w-0 gap-8">
        <h1 className="m-0 font-semibold text-2xl">Settings</h1>
        {q === "" ? <ComputerCanDo /> : null}
        {shown.length === 0 ? (
          <p className="m-0 text-muted-foreground">No setting matches “{query.trim()}”.</p>
        ) : null}
        {GROUPS.map((g) => (
          <section
            key={g.id}
            hidden={!shown.includes(g)}
            id={`settings-${g.id}`}
            aria-labelledby={`settings-${g.id}-title`}
            className="grid scroll-mt-6 gap-5"
          >
            <h2 id={`settings-${g.id}-title`} className="m-0 border-b pb-2 font-semibold text-lg">
              {g.title}
            </h2>
            {g.items.map((i) =>
              i.own ? (
                <div key={i.id} hidden={!hit(g, i)}>
                  {i.body}
                </div>
              ) : (
                <section key={i.id} hidden={!hit(g, i)} aria-label={i.title} className="grid gap-2">
                  <h3 className="m-0 font-semibold text-base">{i.title}</h3>
                  {i.body}
                </section>
              ),
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
