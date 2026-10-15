// SPDX-License-Identifier: AGPL-3.0-only
import { Button } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { discoveryApi } from "../api";
import { engineRepair, engineRestart } from "../engine";
import { ImageEngineCard, UpdateBanner } from "../parts";

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

export function SettingsPage() {
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-8 px-8 pt-16 pb-12">
      <h1 className="font-semibold text-2xl">Settings</h1>

      <section className="grid gap-3" aria-label="Image generation">
        <h2 className="font-semibold text-lg">Image generation</h2>
        <ImageEngineCard />
      </section>

      <FindingModels />

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
