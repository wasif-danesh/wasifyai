"use client";

import { webClient } from "@/lib/run-client";
import { type Picture, usePicture as useSharedPicture } from "@wasifyai/ui";

export type { Picture };

/** One picture for a form (ADR-0039), uploading through the web app's BFF. See `@wasifyai/ui`. */
export function usePicture(product: string) {
  return useSharedPicture(product, webClient);
}
