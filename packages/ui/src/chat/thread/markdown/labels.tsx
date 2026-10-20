"use client";
// `[n]` source labels inside an answer (the notebook chat, ADR-0082 decision 4): each becomes a small element the screen renders as
// a pill the person can open. The labels are found AFTER the sanitiser and the link rules have run, so a model cannot write one by
// hand into anything but text, and a label inside code or a link is left as it is.
import { type ReactNode, createContext, useContext } from "react";

/** The tag the pills are made as: not an HTML element, so nothing a model writes can be one (sanitised away, and raw HTML is text). */
export const LABEL_TAG = "source-label";

const LABEL = /\[(\d{1,3})\](?!\()/g;
const HAS_LABEL = /\[\d{1,3}\](?!\()/;
const SKIP = new Set(["code", "pre", "a", "script", "style"]);

type Hast = {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: Hast[];
};

/** A rehype plugin: `[n]` in text becomes `<source-label n="n">[n]</source-label>`. */
export function labelsAsPills() {
  return (tree: Hast) => {
    const walk = (node: Hast) => {
      if (!node.children || (node.tagName && SKIP.has(node.tagName))) return;
      const next: Hast[] = [];
      for (const child of node.children) {
        if (child.type !== "text" || !child.value || !HAS_LABEL.test(child.value)) {
          walk(child);
          next.push(child);
          continue;
        }
        let at = 0;
        for (const m of child.value.matchAll(LABEL)) {
          const i = m.index ?? 0;
          if (i > at) next.push({ type: "text", value: child.value.slice(at, i) });
          next.push({
            type: "element",
            tagName: LABEL_TAG,
            properties: { n: m[1] },
            children: [{ type: "text", value: m[0] }],
          });
          at = i + m[0].length;
        }
        if (at < child.value.length) next.push({ type: "text", value: child.value.slice(at) });
      }
      node.children = next;
    };
    walk(tree);
  };
}

/** What the screen draws for label n of the message being shown. Without one a label stays text. */
export const LabelContext = createContext<((n: number) => ReactNode) | null>(null);

export function SourceLabel({ n, children }: { n?: string; children?: ReactNode }) {
  const render = useContext(LabelContext);
  const num = Number(n);
  return render && Number.isFinite(num) ? <>{render(num)}</> : <>{children}</>;
}
