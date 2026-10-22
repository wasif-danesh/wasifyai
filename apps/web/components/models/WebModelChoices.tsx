"use client";

import { webChoices } from "@/lib/choices";
import { webVoice, webWorkers } from "@/lib/library";
import { remembered } from "@/lib/remembered";
import { ModelChoicesProvider } from "@wasifyai/ui";
import { type ReactNode, useMemo } from "react";

/** Turns the "Select … model" button on for the voice, music and lip sync screens under it (ADR-0086 on the web). */
export function WebModelChoices({ isAdmin, children }: { isAdmin: boolean; children: ReactNode }) {
  const source = useMemo(
    () => webChoices({ voice: webVoice, workers: webWorkers, memory: remembered, isAdmin }),
    [isAdmin],
  );
  return <ModelChoicesProvider source={source}>{children}</ModelChoicesProvider>;
}
