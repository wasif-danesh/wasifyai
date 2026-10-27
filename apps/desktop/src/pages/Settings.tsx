// SPDX-License-Identifier: AGPL-3.0-only
import { Button, SearchSettings } from "@wasifyai/ui";
import { useEffect, useId, useState } from "react";
import { assistantApi, discoveryApi, hubApi } from "../api";
import { engineRepair, engineRestart } from "../engine";
import { ImageEngineCard, LanguageEngineCard, UpdateBanner } from "../parts";

const INPUT =
  "min-h-20 w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";

/** The automatic look for models other tools left here (ADR-0063): a switch and extra folders. */
function FindingModels() {
  const [enabled, setEnabled] = useState(true);
  const [folders, setFolders] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    discoveryApi
      .state()
      .then((s) => {
        setEnabled(s.enabled);
        setFolders(s.folders.join("\n"));
      })
      .catch(() => {});
  }, []);

  async function save() {
    setError(null);
    setSaved(false);
    try {
      await discoveryApi.settings(
        enabled,
        folders
          .split("\n")
          .map((f) => f.trim())
          .filter(Boolean),
      );
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That could not be saved.");
    }
  }

  return (
    <section className="grid gap-3" aria-label="Finding models">
      <h2 className="font-semibold text-lg">Finding models</h2>
      <p className="text-muted-foreground text-sm">
        When the app starts it looks in the folders where tools such as Ollama, LM Studio, ComfyUI
        and the Hugging Face cache keep models, and lists what it finds in the Model hub. It reads
        only the start of each file, never copies or changes anything, and the list stays on this
        computer.
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => {
            setEnabled(e.target.checked);
            setSaved(false);
          }}
        />
        Look for models when the app starts
      </label>
      <label className="grid gap-1 text-sm">
        <span>More folders to look in (one per line)</span>
        <textarea
          className={INPUT}
          value={folders}
          onChange={(e) => {
            setFolders(e.target.value);
            setSaved(false);
          }}
          placeholder="/Volumes/Models"
        />
      </label>
      <div className="flex items-center gap-3">
        <Button type="button" variant="outline" onClick={() => void save()}>
          Save
        </Button>
        {saved ? <span className="text-sm">Saved.</span> : null}
        {error ? <span className="text-destructive text-sm">{error}</span> : null}
      </div>
    </section>
  );
}

/** Whether the app may contact huggingface.co to list models (ADR-0064): off until the person agrees. */
function HubSwitch() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    hubApi
      .state()
      .then((s) => setEnabled(s.enabled))
      .catch(() => {});
  }, []);
  if (enabled === null) return null;
  return (
    <section className="grid gap-3" aria-label="Browsing models">
      <h2 className="font-semibold text-lg">Browsing models</h2>
      <p className="text-muted-foreground text-sm">
        Discover (in the Model hub) asks huggingface.co for lists of open models. It sends the words
        you search for and the names of the models you open, with no account. Nothing is requested
        while this is off.
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => {
            const next = e.target.checked;
            setError(null);
            hubApi
              .setEnabled(next)
              .then((r) => setEnabled(r.enabled))
              .catch((err) => setError(err instanceof Error ? err.message : "That did not work."));
          }}
        />
        Let the app contact Hugging Face to browse models
      </label>
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </section>
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
    <section className="grid gap-3" aria-label="Hugging Face token">
      <h2 className="font-semibold text-lg">Hugging Face token</h2>
      <p className="text-muted-foreground text-sm">
        Some models on Hugging Face are gated: their authors ask you to accept a licence and sign in
        before a download. Paste a token from your Hugging Face account to fetch them. It is kept in
        this computer's keychain, sent only to huggingface.co, and never shown again.
      </p>
      <label htmlFor={id} className="text-sm">
        Token {state.set ? "(saved)" : "(not saved yet)"}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <input
          id={id}
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          disabled={!state.canSave}
          placeholder={state.set ? "Type a new token to replace it" : "Paste your token (hf_...)"}
          onChange={(e) => setValue(e.target.value)}
          className="h-9 min-w-0 flex-1 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
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
    </section>
  );
}

export function SettingsPage() {
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-8 px-8 pt-16 pb-12">
      <h1 className="font-semibold text-2xl">Settings</h1>

      <section className="grid gap-3" aria-label="Image generation">
        <h2 className="font-semibold text-lg">Image generation</h2>
        <ImageEngineCard />
      </section>

      <section className="grid gap-3" aria-label="Language models">
        <h2 className="font-semibold text-lg">Language models</h2>
        <LanguageEngineCard />
      </section>

      <FindingModels />

      <HubSwitch />

      <HubToken />

      <SearchSettings assistant={assistantApi} />

      <section className="grid gap-3" aria-label="Updates">
        <h2 className="font-semibold text-lg">Updates</h2>
        <UpdateBanner />
        <p className="text-muted-foreground text-sm">
          The app checks for a newer version when it starts, once an update feed is set up.
        </p>
      </section>

      <section className="grid gap-3" aria-label="The engine">
        <h2 className="font-semibold text-lg">The engine</h2>
        <p className="text-muted-foreground text-sm">
          The part of the app that makes things runs as its own process on this computer. Restart it
          if something seems stuck; repair rebuilds its environment.
        </p>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={() => void engineRestart()}>
            Restart the engine
          </Button>
          <Button type="button" variant="outline" onClick={() => void engineRepair()}>
            Repair the installation
          </Button>
        </div>
      </section>
    </div>
  );
}
