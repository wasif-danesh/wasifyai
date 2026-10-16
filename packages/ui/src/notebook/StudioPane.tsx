import {
  AudioLines,
  BarChart3,
  ClipboardList,
  FileText,
  Layers,
  Network,
  Presentation,
  Table2,
} from "lucide-react";

const TILES = [
  { label: "Report", icon: FileText },
  { label: "Flashcards", icon: Layers },
  { label: "Quiz", icon: ClipboardList },
  { label: "Mind map", icon: Network },
  { label: "Slide deck", icon: Presentation },
  { label: "Audio overview", icon: AudioLines },
  { label: "Infographic", icon: BarChart3 },
  { label: "Data table", icon: Table2 },
] as const;

/**
 * What a notebook will make from its sources. The tiles are shown now, so the layout is final, and
 * are not available yet (stage E4 builds the formats).
 */
export function StudioPane() {
  return (
    <section aria-label="Studio" className="flex h-full min-h-0 flex-col">
      <header className="border-b px-4 py-3">
        <h2 className="font-medium text-sm">Studio</h2>
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <ul className="grid grid-cols-2 gap-2">
          {TILES.map((t) => {
            const Icon = t.icon;
            return (
              <li key={t.label}>
                <button
                  type="button"
                  disabled
                  className="flex h-full w-full cursor-default flex-col items-start gap-2 rounded-xl border bg-card/50 p-3 text-start text-muted-foreground opacity-70"
                >
                  <Icon className="size-5" aria-hidden="true" />
                  <span className="text-foreground text-sm">{t.label}</span>
                  <span className="rounded-full border px-2 py-0.5 text-[0.65rem] uppercase tracking-wide">
                    Soon
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <p className="mt-4 px-1 text-muted-foreground text-sm">
          Reports, study material and audio made from your sources will be saved here.
        </p>
      </div>
    </section>
  );
}
