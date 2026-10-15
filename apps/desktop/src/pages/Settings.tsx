// SPDX-License-Identifier: AGPL-3.0-only
import { Button } from "@wasifyai/ui";
import { engineRepair, engineRestart } from "../engine";
import { ImageEngineCard, UpdateBanner } from "../parts";

export function SettingsPage() {
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-8 px-8 pt-16 pb-12">
      <h1 className="font-semibold text-2xl">Settings</h1>

      <section className="grid gap-3" aria-label="Image generation">
        <h2 className="font-semibold text-lg">Image generation</h2>
        <ImageEngineCard />
      </section>

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
