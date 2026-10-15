// SPDX-License-Identifier: AGPL-3.0-only
import { Button } from "@wasifyai/ui";
import { ArrowUp, Sparkles } from "lucide-react";
import type { Route } from "../router";

export function greeting(hour: number): string {
  if (hour < 5) return "Good night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/** The home screen. The assistant (ADR-0057) is not built yet, so its box says so and the actions that
 * work today sit next to it. */
export function HomePage({ go }: { go: (r: Route) => void }) {
  return (
    <div className="grid min-h-full content-center justify-items-center gap-8 px-8 py-16">
      <h1 className="flex items-center gap-4 font-medium text-4xl tracking-tight">
        <span
          aria-hidden="true"
          className="grid size-14 place-items-center rounded-full bg-primary font-bold text-2xl text-primary-foreground"
        >
          w
        </span>
        {greeting(new Date().getHours())}
      </h1>

      <div className="w-full max-w-3xl rounded-3xl border bg-card px-6 py-5 shadow-card">
        <p className="min-h-10 text-lg text-muted-foreground">Ask anything</p>
        <div className="mt-6 flex items-center gap-3 text-muted-foreground text-sm">
          <span>The assistant arrives in a later version. Images work now.</span>
          <span
            aria-hidden="true"
            className="ms-auto grid size-10 place-items-center rounded-full bg-primary/40 text-primary-foreground"
          >
            <ArrowUp className="size-5" />
          </span>
        </div>
      </div>

      <div className="flex flex-wrap justify-center gap-3">
        <Button type="button" onClick={() => go("create")}>
          <Sparkles className="size-4" /> Create an image
        </Button>
        <Button type="button" variant="outline" onClick={() => go("edit")}>
          Edit a picture
        </Button>
        <Button type="button" variant="outline" onClick={() => go("library")}>
          Open the library
        </Button>
      </div>
    </div>
  );
}
