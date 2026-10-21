// SPDX-License-Identifier: AGPL-3.0-only
import { ModelsHome } from "@wasifyai/ui";
import { useState } from "react";
import { ChatModel } from "../ChatModel";
import { FoundModels } from "../FoundModels";
import { ModelHub } from "../ModelHub";
import { ModelsPanel } from "../ModelsPanel";

/**
 * The Models page (ADR-0086): a card for each kind of job. What only an expert needs, the model folders, the files
 * other tools left and the Hugging Face hub (ADR-0064), is under Advanced.
 */
export function ModelsPage() {
  // `#/models?tab=discover` opens Advanced (a link from an older screen)
  const open = window.location.hash.includes("tab=discover");
  // using a found file or finishing a download changes the lists: they read again
  const [version, setVersion] = useState(0);
  const changed = () => setVersion((v) => v + 1);
  return (
    <div className="mx-auto w-full max-w-5xl px-8 pt-16 pb-12">
      <ModelsHome
        advancedOpen={open}
        advanced={
          <>
            <section className="grid gap-3" aria-label="All models and folders">
              <h2 className="m-0 font-semibold text-lg">All models and folders</h2>
              <ModelsPanel key={version} />
            </section>
            <ChatModel key={`chat-${version}`} />
            <FoundModels key={`found-${version}`} onChanged={changed} />
            <section className="grid gap-3" aria-label="Find more on Hugging Face">
              <h2 className="m-0 font-semibold text-lg">Find more on Hugging Face</h2>
              <ModelHub onDownloaded={changed} />
            </section>
          </>
        }
      />
    </div>
  );
}
