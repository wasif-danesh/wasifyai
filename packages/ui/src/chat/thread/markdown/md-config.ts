// How streamdown is set up for a model's answer (ADR-0082 decision 4, spike CU0 section 8). Its defaults are not safe for us
// (remote pictures are fetched, a raw <b> becomes an element, a diagram label can fetch a picture), so every rule is set here,
// in one place, and the safety test (markdown-safety.test.tsx) fails if a streamdown update changes one.
import { defaultRehypePlugins, defaultRemarkPlugins } from "streamdown";
import type { StreamdownProps } from "streamdown";
import { RELATIVE_ORIGIN, SafeLink } from "./SafeLink";
import { LABEL_TAG, SourceLabel, labelsAsPills } from "./labels";

/** A remark plugin: raw HTML in a message becomes plain text, so nothing a model writes is ever parsed as markup. */
export function htmlAsText() {
  type Node = { type: string; children?: Node[] };
  return (tree: Node) => {
    const walk = (n: Node) => {
      for (const c of n.children ?? []) {
        if (c.type === "html") c.type = "text";
        else walk(c);
      }
    };
    walk(tree);
  };
}

export type MarkdownConfig = {
  /** Origins a picture in an answer may load from. None by default: the assistant's pictures come as cards, not as markdown. */
  imageOrigins?: string[];
  /** Turn `[n]` source labels into pills the screen draws (the notebook chat); see `labels.tsx`. */
  labels?: boolean;
};

type Harden = [(options: object) => unknown, object?];

/** The props that make streamdown follow our rules. `plugins` (code, math, diagrams) are added by the caller once loaded. */
export function hardenedProps(config: MarkdownConfig = {}): Partial<StreamdownProps> {
  const harden = defaultRehypePlugins.harden as unknown as Harden;
  return {
    dir: "auto", // right-to-left text is laid out right to left, per block
    linkSafety: { enabled: false }, // our own SafeLink decides; no confirmation dialog
    components: {
      a: SafeLink as never,
      ...(config.labels ? { [LABEL_TAG]: SourceLabel as never } : {}),
    },
    // a diagram: the strict level AND no HTML labels (strict alone still lets an <img> in a label load a remote picture)
    mermaid: {
      config: {
        securityLevel: "strict",
        htmlLabels: false,
        flowchart: { htmlLabels: false },
      } as never,
    },
    remarkPlugins: [...Object.values(defaultRemarkPlugins), htmlAsText as never],
    rehypePlugins: [
      defaultRehypePlugins.sanitize,
      [
        harden[0],
        {
          allowedImagePrefixes: config.imageOrigins ?? [],
          allowedLinkPrefixes: ["*"], // prefixes are parsed as addresses, so "*" plus the protocol list
          allowedProtocols: ["https:", "http:"], // with the colons
          defaultOrigin: RELATIVE_ORIGIN, // required whenever prefixes are given; SafeLink refuses anything that resolved to it
          allowDataImages: false,
        },
      ],
      // after the sanitiser and the link rules, so only text can become a label
      ...(config.labels ? [labelsAsPills] : []),
    ] as never,
  };
}
