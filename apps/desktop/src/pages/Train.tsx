// SPDX-License-Identifier: AGPL-3.0-only
// Train (ADR-0073, ADR-0076): the shared screen on this window's engine.
import { Train } from "@wasifyai/ui";
import { client } from "../api";
import type { Route } from "../router";
import { training } from "../training";

export function TrainPage({ go }: { go: (r: Route) => void }) {
  return <Train api={training} runs={client} onOpenLibrary={() => go("library")} />;
}
