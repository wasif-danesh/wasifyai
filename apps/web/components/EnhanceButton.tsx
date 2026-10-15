"use client";

import { webClient } from "@/lib/run-client";
import { EnhanceButton as SharedEnhanceButton } from "@wasifyai/ui";
import type { ComponentProps } from "react";

/** "Enhance" for a prompt box (ADR-0038), calling the web app's BFF. See `@wasifyai/ui`. */
export function EnhanceButton(props: Omit<ComponentProps<typeof SharedEnhanceButton>, "enhance">) {
  return <SharedEnhanceButton enhance={webClient.enhancePrompt} {...props} />;
}
