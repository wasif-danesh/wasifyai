import type { ReactNode } from "react";
import { Button } from "./button";
import { Experts } from "./experts";
import { Notice } from "./notice";

const PATH =
  /(?:\b(?:GET|POST|PUT|PATCH|DELETE|HEAD)\s+)?(?:https?:\/\/\S+|\/(?:[\w.-]+\/)+[\w.-]*)/g;
// an HTTP status, a shouting constant (ECONNREFUSED, MODEL_NOT_FOUND) or "code 17"; short initials such as PNG or JPEG stay
const CODE =
  /\b(?:HTTP\s*|status\s*)[1-5]\d\d\b|\(\s*[1-5]\d\d\s*\)|\b[A-Z][A-Z_]*_[A-Z_]+\b|\b[A-Z]{7,}\b|\bcode\s*[:=]?\s*\S+/g;
const TRACE = /(?:Traceback|Stack trace|\s+at\s+\S+\s*\(.*)[\s\S]*/;
const PREFIX = /^(?:error|exception|[\w.]*Error|not mocked|failed)\s*:\s*/i;

/**
 * An error in plain words. Whatever came from the engine or the network is cleaned of paths, addresses, HTTP
 * codes, constant names and stack traces (`design/DESIGN.md`: "never a code or a stack trace"); the original is
 * kept under "Details for experts" so nothing is lost.
 */
export function plainError(raw: string, fallback = "That did not work."): string {
  let text = raw
    .replace(TRACE, "")
    .replace(PATH, "")
    .replace(CODE, "")
    .replace(PREFIX, "")
    .replace(/\(\s*\)|\[\s*\]/g, "") // brackets emptied by the lines above
    .replace(/\s*[([]\s*$/, "")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([.,;:])/g, "$1")
    .trim();
  text = text.replace(/^[\s:;,.-]+|[\s:;,-]+$/g, "").trim();
  if (text.length < 3) return fallback;
  const first = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?]$/.test(first) ? first : `${first}.`;
}

/** "That did not work": what happened in plain words, what to do next, and the raw text for experts. */
export function ErrorNotice({
  title = "That did not work",
  message,
  next,
  onRetry,
  onReset,
  retryLabel = "Try again",
  resetLabel = "Start over",
  details,
}: {
  title?: string;
  /** the message as it came; it is cleaned before it is shown */
  message: string;
  /** what the person can do about it, when the message does not say */
  next?: ReactNode;
  onRetry?: () => void;
  onReset?: () => void;
  retryLabel?: string;
  resetLabel?: string;
  /** more raw text for the experts' section (a request id, a log line) */
  details?: string;
}) {
  const plain = plainError(message);
  const raw = [message, details].filter(Boolean).join("\n");
  const hasRaw = raw.trim() !== plain;
  return (
    <div className="grid gap-2" data-slot="error-notice">
      <Notice
        tone="error"
        title={title}
        actions={
          onRetry || onReset ? (
            <>
              {onRetry ? (
                <Button type="button" onClick={onRetry}>
                  {retryLabel}
                </Button>
              ) : null}
              {onReset ? (
                <Button type="button" variant="outline" onClick={onReset}>
                  {resetLabel}
                </Button>
              ) : null}
            </>
          ) : undefined
        }
      >
        {plain}
        {next ? <> {next}</> : null}
      </Notice>
      {hasRaw ? (
        <Experts title="Details for experts">
          <pre className="m-0 overflow-x-auto whitespace-pre-wrap break-all font-mono text-muted-foreground text-xs">
            {raw}
          </pre>
        </Experts>
      ) : null}
    </div>
  );
}
