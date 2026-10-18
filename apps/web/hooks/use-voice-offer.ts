"use client";

import { webVoice } from "@/lib/library";
import { type VoiceScreenName, offeredScreens } from "@/lib/voice-screens";
import { useEffect, useState } from "react";

let known: VoiceScreenName[] | null = null;

/** The voice screens this deployment can run, asked of the service once per page load. Nothing is offered
 * until it answers, and nothing if it cannot (the menu then shows those items as "Soon"). */
export function useVoiceOffer(enabled: boolean): readonly VoiceScreenName[] {
  const [offer, setOffer] = useState<readonly VoiceScreenName[]>(known ?? []);
  useEffect(() => {
    if (!enabled || known) return;
    let alive = true;
    webVoice
      .models()
      .then((models) => {
        known = offeredScreens(models);
        if (alive) setOffer(known);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [enabled]);
  return offer;
}
