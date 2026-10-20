// SPDX-License-Identifier: AGPL-3.0-only
import { Button, SearchSettings, useChatNext } from "@wasifyai/ui";
import { useEffect, useState } from "react";
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
        and the Hugging Face cache keep models, and lists what it finds under Models. It reads only
        the start of each file, never copies or changes anything, and the list stays on this
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
        Discover (under Models) asks huggingface.co for lists of open models. It sends the words you
        search for and the names of the models you open, with no account. Nothing is requested while
        this is off.
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

/** Features still being tried (ADR-0082): off until the person turns them on, remembered on this computer. */
function Labs() {
  const [chatNext, setChatNext] = useChatNext();
  return (
    <section className="grid gap-3" aria-label="Labs">
      <h2 className="font-semibold text-lg">Labs</h2>
      <p className="text-muted-foreground text-sm">
        Things that are still being built. They may be missing a feature the usual screen has, and
        they can change. Turning one off brings the usual screen back; nothing is lost.
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={chatNext} onChange={(e) => setChatNext(e.target.checked)} />
        Try the new chat (code, maths and diagrams in answers)
      </label>
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

      <SearchSettings assistant={assistantApi} />

      <Labs />

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
