// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { FoundModels } from "../FoundModels";
import { ModelsPanel } from "../ModelsPanel";

export function ModelsPage() {
  // using a found file adds its folder: the panel above reads its list again
  const [version, setVersion] = useState(0);
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-8 px-8 pt-16 pb-12">
      <div>
        <h1 className="font-semibold text-2xl">Models</h1>
        <p className="text-muted-foreground">
          The models the app can use, where they are kept, and what is loaded in memory.
        </p>
      </div>
      <ModelsPanel key={version} />
      <FoundModels onChanged={() => setVersion((v) => v + 1)} />
    </div>
  );
}
