import type { NotebookOutput, StudioFormat } from "@wasifyai/client";

export type StudioTile = {
  key: StudioFormat;
  label: string;
  /** one line under the name in the brief */
  about: string;
};

/** The formats Studio makes today, in the order the tiles show. */
export const STUDIO_TILES: StudioTile[] = [
  { key: "report", label: "Report", about: "A short written report of what the sources say." },
  {
    key: "study_guide",
    label: "Study guide",
    about: "Key terms, main ideas and questions to check what you remember.",
  },
  {
    key: "flashcards",
    label: "Flashcards",
    about: "Cards with a question on the front and the answer behind.",
  },
  {
    key: "quiz",
    label: "Quiz",
    about: "Multiple-choice questions with the reason for each answer.",
  },
  { key: "mindmap", label: "Mind map", about: "The main topics and what hangs under them." },
  { key: "word", label: "Word document", about: "The report as a .docx you can edit." },
  { key: "pdf", label: "PDF", about: "The report as a PDF you can share." },
  {
    key: "slides",
    label: "Slide deck",
    about: "Slides with a few lines each and speaker notes, as a .pptx.",
  },
  {
    key: "datatable",
    label: "Data table",
    about: "A table of the figures the sources give, as an Excel file.",
  },
  {
    key: "audio",
    label: "Audio overview",
    about:
      "A script of two hosts talking it through. The voices come with the voice engine; for now it is the script.",
  },
  {
    key: "infographic",
    label: "Infographic",
    about:
      "A drawn picture of the main facts, made by the image engine. Needs image generation set up.",
  },
];

export const FORMAT_LABEL: Record<StudioFormat, string> = Object.fromEntries(
  STUDIO_TILES.map((t) => [t.key, t.label]),
) as Record<StudioFormat, string>;

export const making = (o: NotebookOutput) => o.status === "processing";

export type MapNode = { label: string; children: MapNode[] };

/**
 * A mind map's outline (`# Title` over nested `- label` lines, two spaces a level) as a tree.
 * Anything that is not an outline line is ignored; a level that jumps is attached to the nearest
 * parent above it.
 */
export function parseOutline(markdown: string): { title: string; roots: MapNode[] } {
  let title = "";
  const roots: MapNode[] = [];
  const stack: { depth: number; node: MapNode }[] = [];
  for (const line of markdown.split("\n")) {
    const head = /^#\s+(.*)$/.exec(line);
    if (head) {
      title = (head[1] ?? "").trim();
      continue;
    }
    const item = /^(\s*)[-*+]\s+(.*)$/.exec(line);
    if (!item) continue;
    const depth = Math.floor((item[1] ?? "").length / 2);
    const node: MapNode = { label: (item[2] ?? "").trim(), children: [] };
    while (stack.length && (stack[stack.length - 1]?.depth ?? 0) >= depth) stack.pop();
    const parent = stack[stack.length - 1]?.node;
    if (parent) parent.children.push(node);
    else roots.push(node);
    stack.push({ depth, node });
  }
  return { title, roots };
}
