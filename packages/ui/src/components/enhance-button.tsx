"use client";

import { type Enhanced, HttpError } from "@wasifyai/client";
import { useEffect, useId, useRef, useState } from "react";
import { fieldError } from "../styles";
import { Button } from "./button";
import { Spinner } from "./spinner";

/**
 * "Improve prompt" for a prompt box (ADR-0038): the product's model rewrites what the user typed into a better
 * prompt (in English for images and video). The result replaces the text and "Undo" brings the original
 * back; nothing is submitted. The user can edit the result before making anything.
 */
export type EnhanceFn = (
  product: string,
  input: { kind: string; prompt: string; uploadId?: string },
  signal?: AbortSignal,
) => Promise<Enhanced>;

export function EnhanceButton({
  enhance: enhanceCall,
  product,
  kind,
  value,
  uploadId,
  needsPicture = false,
  maxChars,
  disabled = false,
  onChange,
}: {
  /** The call that rewrites the prompt: the app's client (`client.enhancePrompt`). */
  enhance: EnhanceFn;
  product: string;
  kind: string;
  value: string;
  uploadId?: string;
  needsPicture?: boolean;
  maxChars: number;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [original, setOriginal] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const helpId = useId();
  useEffect(() => () => abort.current?.abort(), []);

  const text = value.trim();
  const blocked =
    disabled || busy || text.length === 0 || value.length > maxChars || (needsPicture && !uploadId);

  const help =
    needsPicture && !uploadId
      ? "Choose a picture first."
      : text.length === 0
        ? "Type a prompt first, then improve it."
        : "Rewrites your prompt with more detail so the result is better. The new prompt is written in English. Nothing is made yet, and you can undo it.";

  async function enhance() {
    if (blocked) return;
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const out = await enhanceCall(product, { kind, prompt: text, uploadId }, ctrl.signal);
      if (out.changed) {
        setOriginal(value);
        onChange(out.prompt);
        setNote("Prompt improved.");
      } else {
        setNote("That prompt already looks good.");
      }
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setError(
        e instanceof HttpError
          ? e.message
          : "We couldn't reach the server. Check your connection and try again.",
      );
    } finally {
      if (!ctrl.signal.aborted) setBusy(false);
    }
  }

  function undo() {
    if (original === null) return;
    onChange(original);
    setOriginal(null);
    setNote("Your original text is back.");
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={enhance}
        disabled={blocked}
        aria-busy={busy}
        title={help}
        aria-describedby={helpId}
      >
        {busy ? <Spinner /> : <span aria-hidden="true">✨</span>}
        {busy ? "Improving…" : "Improve prompt"}
      </Button>
      <span id={helpId} className="sr-only">
        {help}
      </span>
      {original !== null && !busy ? (
        <Button type="button" variant="link" size="sm" onClick={undo}>
          Undo
        </Button>
      ) : null}
      <output className="sr-only">{note}</output>
      {error ? (
        <span className={fieldError} role="alert">
          {error}
        </span>
      ) : null}
    </span>
  );
}
