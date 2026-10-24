"use client";

import { WebModelChoices } from "@/components/models/WebModelChoices";
import { ModelsHome } from "@wasifyai/ui";

/** The Models page for an admin (ADR-0089): the same tab table as the desktop window, over the models of the workers. */
export function ModelsAdmin() {
  return (
    <WebModelChoices isAdmin>
      <ModelsHome place="service" only={["voice", "listening", "music", "faces"]} />
    </WebModelChoices>
  );
}
