"use client";
// The card that asks before the assistant makes or changes something (ADR-0071). The engine parks the turn on it; the person's
// click goes back through the run's resume and the turn goes on. Plain text only: what the card shows came from the assistant.
import type { ChatPart } from "@wasifyai/client";
import { Button } from "../../../components/button";
import { Spinner } from "../../../components/spinner";

type Tool = Extract<ChatPart, { type: "tool" }>;

const HEADING = new Set(["title", "summary", "kind", "tool_call_id"]);
const SHOWN = 4; // parameters shown on the card; the rest are not needed to decide

function value(v: unknown): string {
  const s = typeof v === "string" ? v : String(v);
  return s.length > 200 ? `${s.slice(0, 199)}…` : s;
}

export function ConfirmActionCard({
  tool,
  onDecide,
}: {
  tool: Tool;
  onDecide?: (approved: boolean) => void;
}) {
  const a = tool.approval;
  if (!a) return null;
  // what the card says about itself is not a parameter
  const params = Object.entries(a.params ?? tool.arguments)
    .filter(([k]) => !HEADING.has(k))
    .slice(0, SHOWN);
  const title = a.title || "The assistant wants to do something";
  const decided = a.state !== "pending";
  return (
    <section
      aria-label={title}
      className="grid max-w-md gap-2 rounded-lg border bg-accent/40 p-3 text-sm"
    >
      <p className="font-medium">{title}</p>
      {a.summary && a.summary !== title ? (
        <p className="text-muted-foreground">{a.summary}</p>
      ) : null}
      {params.length ? (
        <dl className="grid gap-0.5">
          {params.map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="shrink-0 text-muted-foreground">{k}</dt>
              <dd dir="auto" className="min-w-0 break-words">
                {value(v)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {decided ? (
        <output className="flex items-center gap-2 text-muted-foreground">
          {a.state === "approved" ? <Spinner /> : null}
          {a.state === "approved" ? "Approved. Working on it" : "You said no"}
        </output>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" onClick={() => onDecide?.(true)} disabled={!onDecide}>
            Go ahead
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onDecide?.(false)}
            disabled={!onDecide}
          >
            Not now
          </Button>
        </div>
      )}
    </section>
  );
}
