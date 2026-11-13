// SPDX-License-Identifier: AGPL-3.0-only
import { ModelChoicesProvider, PageHero, SaveAsProvider, page } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { Shell } from "./Shell";
import { transport } from "./api";
import { choicesSource } from "./choices";
import { COMFYUI, type EngineStatus, LLAMACPP, engineStatus, onEngineStatus } from "./engine";
import { EngineState } from "./parts";
import { saveAs } from "./save-as";
import { runComponentSmoke, runSmoke, smokeComponent, smokeEnabled } from "./smoke";

export function App() {
  const [status, setStatus] = useState<EngineStatus>({ state: "starting", attempt: 1 });

  useEffect(() => {
    let stop: (() => void) | undefined;
    let gone = false;
    const apply = (s: EngineStatus) => {
      // a restarted engine has a new address and a new secret
      transport.invalidate();
      if (!gone) setStatus(s);
    };
    engineStatus().then(apply);
    onEngineStatus(apply).then((off) => {
      stop = off;
      if (gone) off();
    });
    return () => {
      gone = true;
      stop?.();
    };
  }, []);

  // `WASIFYAI_SMOKE=1` (see smoke.ts): once the screen is up, use it like a person would and report.
  useEffect(() => {
    if (status.state !== "ready") return;
    smokeEnabled()
      .then(async (on) => {
        if (!on) return;
        // WASIFYAI_SMOKE_COMPONENT=comfyui: set the image engine up instead of making an image
        const component = await smokeComponent();
        if (component === COMFYUI || component === LLAMACPP) return runComponentSmoke(component);
        return runSmoke();
      })
      .catch(() => {});
  }, [status.state]);

  if (status.state === "ready") {
    return (
      <SaveAsProvider value={saveAs}>
        <ModelChoicesProvider source={choicesSource}>
          <Shell />
        </ModelChoicesProvider>
      </SaveAsProvider>
    );
  }
  return (
    <main id="main" className={page}>
      <PageHero title="Wasify AI" />
      <EngineState status={status} />
    </main>
  );
}
