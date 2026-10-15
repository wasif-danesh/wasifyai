// SPDX-License-Identifier: AGPL-3.0-only
import { cn } from "@wasifyai/ui";
import { useState } from "react";
import { ChatModel } from "../ChatModel";
import { FoundModels } from "../FoundModels";
import { ModelHub } from "../ModelHub";
import { ModelsPanel } from "../ModelsPanel";

type Tab = "device" | "discover";

/** The model hub (ADR-0064): what is on this computer, and finding more. */
export function ModelsPage() {
  const [tab, setTab] = useState<Tab>("device");
  // using a found file or finishing a download changes the lists: they read again
  const [version, setVersion] = useState(0);
  const changed = () => setVersion((v) => v + 1);
  return (
    <div className="mx-auto grid w-full max-w-5xl gap-6 px-8 pt-16 pb-12">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-semibold text-2xl">Models</h1>
          <p className="text-muted-foreground">
            Find open models and see what is on this computer, where it is kept and what is loaded.
          </p>
        </div>
        <div
          className="flex gap-1 rounded-full border p-1 text-sm"
          role="tablist"
          aria-label="Models"
        >
          {(
            [
              ["device", "On device"],
              ["discover", "Discover"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={cn(
                "rounded-full px-4 py-1.5",
                tab === id ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent",
              )}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "device" ? (
        <div className="mx-auto grid w-full max-w-3xl gap-8">
          <ModelsPanel key={version} />
          <ChatModel key={`chat-${version}`} />
          <FoundModels key={`found-${version}`} onChanged={changed} />
        </div>
      ) : (
        <ModelHub onDownloaded={changed} />
      )}
    </div>
  );
}
