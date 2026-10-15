// SPDX-License-Identifier: AGPL-3.0-only
import { ModelsPanel } from "../ModelsPanel";

export function ModelsPage() {
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-6 px-8 pt-16 pb-12">
      <div>
        <h1 className="font-semibold text-2xl">Models</h1>
        <p className="text-muted-foreground">
          The models the app can use, where they are kept, and what is loaded in memory.
        </p>
      </div>
      <ModelsPanel />
    </div>
  );
}
