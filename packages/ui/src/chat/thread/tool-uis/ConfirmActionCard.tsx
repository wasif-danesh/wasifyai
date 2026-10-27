"use client";
// The card that asks before the assistant makes or changes something (ADR-0071 decision 4). The engine parks the turn
// on it; the person's click goes back through the run's resume and the turn goes on. The fields are drawn from the
// action's own schema and can be edited before Run; a `needs_consent` action shows its statement with a tick of its own.
// Plain text only: what the card shows came from the assistant.
import type { CardField, ChatPart } from "@wasifyai/client";
import { useMemo, useState } from "react";
import { Badge } from "../../../components/badge";
import { Button } from "../../../components/button";
import { Input } from "../../../components/input";
import { Spinner } from "../../../components/spinner";
import { Textarea } from "../../../components/textarea";

type Tool = Extract<ChatPart, { type: "tool" }>;
type Values = Record<string, string | number | boolean>;

const HEADING = new Set(["title", "summary", "kind", "tool_call_id"]);
const SHOWN = 4; // parameters shown on a card without fields; the rest are not needed to decide
const FIELD =
  "min-w-0 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";

function value(v: unknown): string {
  const s = typeof v === "string" ? v : String(v);
  return s.length > 200 ? `${s.slice(0, 199)}…` : s;
}

function start(f: CardField): string | number | boolean {
  if (f.value !== undefined) return f.value;
  return f.kind === "bool" ? false : "";
}

/** The values as the action takes them: numbers as numbers, nothing for an empty field. */
function asParams(fields: CardField[], values: Values): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.name];
    if (v === "" || v === undefined) continue;
    if (f.kind === "number") {
      const n = typeof v === "number" ? v : Number(v);
      if (!Number.isNaN(n)) out[f.name] = n;
    } else out[f.name] = v;
  }
  return out;
}

function Field({
  field,
  value: v,
  onChange,
  disabled,
}: {
  field: CardField;
  value: string | number | boolean;
  onChange: (v: string | number | boolean) => void;
  disabled: boolean;
}) {
  const id = `card-${field.name}`;
  const label = (
    <span>
      {field.label}
      {field.required ? <span aria-hidden="true"> *</span> : null}
    </span>
  );
  if (field.kind === "bool")
    return (
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={v === true}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
        {label}
      </label>
    );
  if (field.kind === "choice")
    return (
      <label htmlFor={id} className="grid gap-1">
        {label}
        <select
          id={id}
          className={`h-9 ${FIELD}`}
          value={String(v)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          {!field.required ? <option value="">(none)</option> : null}
          {(field.choices ?? []).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
    );
  if (field.kind === "long_text")
    return (
      <label htmlFor={id} className="grid gap-1">
        {label}
        <Textarea
          id={id}
          dir="auto"
          value={String(v)}
          maxLength={field.max_length}
          disabled={disabled}
          rows={3}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
    );
  return (
    <label htmlFor={id} className="grid gap-1">
      {label}
      <Input
        id={id}
        dir="auto"
        type={field.kind === "number" ? "number" : "text"}
        value={String(v)}
        min={field.min}
        max={field.max}
        maxLength={field.max_length}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function estimateText(a: { estimate?: { seconds: number; runs: number }; pauses_chat?: boolean }) {
  const lines: string[] = [];
  if (a.estimate) {
    const s = a.estimate.seconds;
    const time = s >= 90 ? `about ${Math.round(s / 60)} min` : `about ${s} s`;
    const runs = a.estimate.runs === 1 ? "your last run" : `your last ${a.estimate.runs} runs`;
    lines.push(`Takes ${time} on this computer (${runs}).`);
  }
  if (a.pauses_chat) lines.push("Pauses the chat model while it runs.");
  return lines;
}

export function ConfirmActionCard({
  tool,
  onDecide,
  onAutoRun,
}: {
  tool: Tool;
  onDecide?: (approved: boolean, params?: Record<string, unknown>) => void;
  /** the person ticked "Don't ask again in this chat" and pressed Run */
  onAutoRun?: () => void;
}) {
  const a = tool.approval;
  const fields = useMemo(() => a?.fields ?? [], [a?.fields]);
  const initial = useMemo<Values>(
    () => Object.fromEntries(fields.map((f) => [f.name, start(f)])),
    [fields],
  );
  const [values, setValues] = useState<Values>(initial);
  const [consented, setConsented] = useState(false);
  const [noMoreAsking, setNoMoreAsking] = useState(false);
  if (!a) return null;
  // what the card says about itself is not a parameter
  const params = Object.entries(a.params ?? tool.arguments)
    .filter(([k]) => !HEADING.has(k))
    .slice(0, SHOWN);
  const title = a.title || "The assistant wants to do something";
  const decided = a.state !== "pending";
  const changed = fields.some((f) => values[f.name] !== initial[f.name]);
  const missing = fields.some((f) => f.required && values[f.name] === "");
  const canRun = Boolean(onDecide) && !missing && (!a.consent || consented);
  return (
    <section
      aria-label={title}
      className="grid max-w-md gap-2 rounded-lg border bg-accent/40 p-3 text-sm"
    >
      <p className="font-medium">{title}</p>
      {a.summary && a.summary !== title ? (
        <p className="text-muted-foreground">{a.summary}</p>
      ) : null}
      {a.badges?.length ? (
        <ul className="m-0 flex list-none flex-wrap gap-1 p-0">
          {a.badges.map((b) => (
            <li key={b}>
              <Badge variant="outline">{b}</Badge>
            </li>
          ))}
        </ul>
      ) : null}
      {fields.length ? (
        <div className="grid gap-2">
          {fields.map((f) => (
            <Field
              key={f.name}
              field={f}
              value={values[f.name] ?? ""}
              disabled={decided}
              onChange={(v) => setValues((s) => ({ ...s, [f.name]: v }))}
            />
          ))}
        </div>
      ) : params.length ? (
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
      {estimateText(a).map((line) => (
        <p key={line} className="text-muted-foreground text-xs">
          {line}
        </p>
      ))}
      {a.provenance ? (
        <p className="text-muted-foreground text-xs">Asking because this came {a.provenance}.</p>
      ) : null}
      {a.consent && !decided ? (
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={consented}
            onChange={(e) => setConsented(e.target.checked)}
            className="mt-1"
          />
          <span>{a.consent}</span>
        </label>
      ) : null}
      {onAutoRun && !decided && a.effect === "make" && !a.consent ? (
        <label className="flex items-center gap-2 text-muted-foreground text-xs">
          <input
            type="checkbox"
            checked={noMoreAsking}
            onChange={(e) => setNoMoreAsking(e.target.checked)}
          />
          Don't ask again in this chat
        </label>
      ) : null}
      {decided ? (
        <output className="flex items-center gap-2 text-muted-foreground">
          {a.state === "approved" ? <Spinner /> : null}
          {a.state === "approved" ? "Approved. Working on it" : "You said no"}
        </output>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            onClick={() => {
              if (noMoreAsking) onAutoRun?.();
              onDecide?.(true, changed ? asParams(fields, values) : undefined);
            }}
            disabled={!canRun}
          >
            Run
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
