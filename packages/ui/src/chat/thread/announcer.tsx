"use client";

import { useEffect, useRef, useState } from "react";

/** A reply as a person would hear it: the marks of markdown taken out. */
export function plainText(markdown: string): string {
  return markdown
    .replace(/^\s*(```|~~~).*$/gm, " ")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/[*_`~>|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export type AnnouncerProps = {
  /** an answer is arriving */
  working: boolean;
  /** what went wrong, when the turn ended in an error */
  error: string | null;
  /** the text of the last reply, read once when it is complete */
  answer: string;
};

/**
 * The live region assistant-ui does not have (spike CU0, section 10): a person using a screen reader hears that the assistant is
 * answering, and then the finished answer once, instead of every chunk as it arrives. Visually hidden; the thread itself is not live.
 */
export function Announcer({ working, error, answer }: AnnouncerProps) {
  const [status, setStatus] = useState("");
  const [log, setLog] = useState("");
  const was = useRef(false);
  const latest = useRef({ error, answer });
  latest.current = { error, answer };

  useEffect(() => {
    if (working && !was.current) {
      setStatus("The assistant is answering.");
      setLog("");
    } else if (!working && was.current) {
      const { error: e, answer: a } = latest.current;
      if (e) setStatus(`That did not work. ${e}`);
      else {
        setStatus("Answer ready.");
        const text = plainText(a);
        if (text) setLog(`The assistant said: ${text}`);
      }
    }
    was.current = working;
  }, [working]);

  return (
    <>
      <output className="sr-only">{status}</output>
      <div role="log" aria-relevant="additions" className="sr-only">
        {log}
      </div>
    </>
  );
}
