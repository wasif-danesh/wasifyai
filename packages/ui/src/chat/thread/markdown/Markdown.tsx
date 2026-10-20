"use client";

import { Suspense, lazy, memo } from "react";
import type { MarkdownProps } from "./StreamdownBody";

export type { MarkdownProps };

// streamdown itself is about 150 KB gzip, so the first screen does not carry it: it loads right after the box is usable
// (`preloadMarkdown`, called when the screen mounts) and is there long before the first answer. Until then the text is shown as it is.
const Body = lazy(() => import("./StreamdownBody"));

export function preloadMarkdown(): Promise<unknown> {
  return import("./StreamdownBody");
}

function Plain({ text }: { text: string }) {
  return (
    <p dir="auto" className="whitespace-pre-wrap break-words">
      {text}
    </p>
  );
}

/**
 * A model's answer as formatted text. Nothing it writes can run or fetch: raw HTML is shown as text, only absolute http(s)
 * links are links, pictures load only from `imageOrigins`, diagrams use the strict level without HTML labels. Code, maths and
 * diagrams work offline. See `StreamdownBody.tsx` and `md-config.ts`.
 */
export const Markdown = memo(function Markdown(props: MarkdownProps) {
  return (
    <Suspense fallback={<Plain text={props.text} />}>
      <Body {...props} />
    </Suspense>
  );
});
