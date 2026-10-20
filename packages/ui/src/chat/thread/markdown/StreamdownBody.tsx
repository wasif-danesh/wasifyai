/// <reference path="../../../css.d.ts" />
"use client";

import { memo, useEffect, useMemo, useState } from "react";
import { Streamdown } from "streamdown";
import "streamdown/styles.css";
import { type MarkdownConfig, hardenedProps } from "./md-config";

type Plugins = { code?: unknown; math?: unknown; mermaid?: unknown };

// A plugin is loaded the first time a message needs it, never before: the code languages, the maths and the diagrams are
// about 15 MB of files that most chats never touch (ADR-0082, spike CU0 section 8).
const needs = (text: string) => ({
  code: text.includes("```") || text.includes("~~~"),
  math: /\$\$|\$[^$\n]+\$/.test(text),
  mermaid: /(```|~~~)\s*mermaid/.test(text),
});

/** Which of the plugins the text needs are loaded; each loads once for the whole page. */
const loaded: Plugins = {};
const loading: Partial<Record<keyof Plugins, Promise<void>>> = {};

function load(kind: keyof Plugins): Promise<void> {
  const started = loading[kind];
  if (started) return started;
  const p = (async () => {
    if (kind === "code") loaded.code = (await import("@streamdown/code")).code;
    else if (kind === "math") {
      const [m] = await Promise.all([
        import("@streamdown/math"),
        import("katex/dist/katex.min.css"),
      ]);
      loaded.math = m.math;
    } else loaded.mermaid = (await import("@streamdown/mermaid")).mermaid;
  })().catch(() => {
    // the text is shown without it; a later message may try again
    delete loading[kind];
  });
  loading[kind] = p;
  return p;
}

export type MarkdownProps = MarkdownConfig & {
  text: string;
  /** the answer is still arriving */
  animating?: boolean;
};

/**
 * A model's answer as formatted text (the part that carries streamdown; `Markdown.tsx` loads it on demand). Nothing it writes can run or fetch: raw HTML is shown as text, only absolute http(s)
 * links are links, pictures load only from `imageOrigins`, diagrams use the strict level without HTML labels. Code, maths and
 * diagrams work offline.
 */
const StreamdownBody = memo(function StreamdownBody({
  text,
  animating,
  imageOrigins,
  labels,
}: MarkdownProps) {
  const { code, math, mermaid } = needs(text);
  const [plugins, setPlugins] = useState<Plugins>({ ...loaded });
  useEffect(() => {
    let gone = false;
    const wanted = { code, math, mermaid };
    for (const kind of ["code", "math", "mermaid"] as const) {
      if (!wanted[kind]) continue;
      void load(kind).then(() => {
        const plugin = loaded[kind];
        if (!gone && plugin) setPlugins((p) => (p[kind] === plugin ? p : { ...p, [kind]: plugin }));
      });
    }
    return () => {
      gone = true;
    };
  }, [code, math, mermaid]);
  const props = useMemo(() => hardenedProps({ imageOrigins, labels }), [imageOrigins, labels]);
  return (
    <Streamdown
      data-markdown=""
      isAnimating={animating}
      // closing a half-written **bold** is for text that is still arriving; a finished answer is shown as it was written
      parseIncompleteMarkdown={Boolean(animating)}
      plugins={plugins as never}
      {...props}
    >
      {text}
    </Streamdown>
  );
});

export default StreamdownBody;
