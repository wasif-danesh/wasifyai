"use client";
// The form an outside server waits for (ADR-0070 decision 10, stage C3): "github asks: What is your name?". The
// engine raises an `elicitation` event on the window's stream; the pending list is read on open, so a form raised
// while the window was away is not lost. The person fills it in or declines; the assistant never answers for them.
import type { ConnectionsApi, ExternalApi, FormAction, PendingForm } from "@wasifyai/client";
import { useCallback, useEffect, useId, useState } from "react";
import { Button } from "../components/button";

const RETRY_MS = 5000;

type FieldSpec = {
  name: string;
  kind: "text" | "number" | "bool" | "choice";
  label: string;
  description: string;
  required: boolean;
  choices: string[];
};

/** The fields of a form, from its schema (top-level properties only, as the protocol has it). */
export function fieldsOf(schema: Record<string, unknown>): FieldSpec[] {
  const props = (schema.properties ?? {}) as Record<string, Record<string, unknown>>;
  const required = new Set((schema.required as string[] | undefined) ?? []);
  return Object.entries(props).map(([name, spec]) => {
    const type = String(spec.type ?? "string");
    const choices = Array.isArray(spec.enum) ? spec.enum.map(String) : [];
    return {
      name,
      kind: choices.length
        ? "choice"
        : type === "boolean"
          ? "bool"
          : type === "number" || type === "integer"
            ? "number"
            : "text",
      label: String(spec.title ?? name.replace(/_/g, " ")),
      description: typeof spec.description === "string" ? spec.description : "",
      required: required.has(name),
      choices,
    };
  });
}

export function useForms(external: ExternalApi, connections: ConnectionsApi, enabled = true) {
  const [pending, setPending] = useState<PendingForm[]>([]);
  const refresh = useCallback(() => {
    external
      .forms()
      .then((r) => setPending(r.forms))
      .catch(() => {});
  }, [external]);
  useEffect(() => {
    if (!enabled) return;
    refresh();
    const control = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const listen = () => {
      connections
        .events((e) => {
          if (e.kind === "elicitation") refresh();
        }, control.signal)
        .catch(() => {})
        .finally(() => {
          if (!control.signal.aborted) timer = setTimeout(listen, RETRY_MS);
        });
    };
    listen();
    return () => {
      control.abort();
      if (timer) clearTimeout(timer);
    };
  }, [connections, enabled, refresh]);
  const answer = useCallback(
    async (formId: string, action: FormAction, content?: Record<string, unknown>) => {
      setPending((ps) => ps.filter((p) => p.form_id !== formId));
      try {
        await external.answerForm(formId, action, content);
      } finally {
        refresh();
      }
    },
    [external, refresh],
  );
  return { pending, answer };
}

export function FormCard({
  form,
  onAnswer,
}: {
  form: PendingForm;
  onAnswer: (action: FormAction, content?: Record<string, unknown>) => void;
}) {
  const id = useId();
  const fields = fieldsOf(form.schema);
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(fields.filter((f) => f.kind === "bool").map((f) => [f.name, false])),
  );
  const ready = fields.every((f) => !f.required || String(values[f.name] ?? "").trim());
  function send() {
    const content: Record<string, unknown> = {};
    for (const f of fields) {
      const v = values[f.name];
      if (v === undefined || v === "") continue;
      content[f.name] = f.kind === "number" ? Number(v) : v;
    }
    onAnswer("accept", content);
  }
  const title = `${form.server} asks`;
  return (
    <section
      aria-label={title}
      className="grid max-w-md gap-2 rounded-lg border bg-accent/40 p-3 text-sm shadow"
    >
      <p className="m-0 font-medium">{title}</p>
      <p className="m-0">{form.message}</p>
      <form
        className="grid gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) send();
        }}
      >
        {fields.map((f) => (
          <label key={f.name} htmlFor={`${id}-${f.name}`} className="grid gap-0.5 text-xs">
            <span>
              {f.label}
              {f.required ? "" : " (optional)"}
              {f.description ? `: ${f.description}` : ""}
            </span>
            {f.kind === "bool" ? (
              <input
                id={`${id}-${f.name}`}
                type="checkbox"
                checked={Boolean(values[f.name])}
                onChange={(e) => setValues((s) => ({ ...s, [f.name]: e.target.checked }))}
              />
            ) : f.kind === "choice" ? (
              <select
                id={`${id}-${f.name}`}
                className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
                value={String(values[f.name] ?? "")}
                onChange={(e) => setValues((s) => ({ ...s, [f.name]: e.target.value }))}
              >
                <option value="">—</option>
                {f.choices.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={`${id}-${f.name}`}
                type={f.kind === "number" ? "number" : "text"}
                value={String(values[f.name] ?? "")}
                onChange={(e) => setValues((s) => ({ ...s, [f.name]: e.target.value }))}
                className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
              />
            )}
          </label>
        ))}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" disabled={!ready}>
            Send
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => onAnswer("decline")}>
            Decline
          </Button>
        </div>
      </form>
      <p className="m-0 text-muted-foreground text-xs">
        Your answer goes to {form.server} and nowhere else. The assistant never answers for you.
      </p>
    </section>
  );
}

export function ElicitationCards({
  external,
  connections,
  enabled = true,
}: {
  external: ExternalApi;
  connections: ConnectionsApi;
  enabled?: boolean;
}) {
  const { pending, answer } = useForms(external, connections, enabled);
  if (!pending.length) return null;
  return (
    <div className="fixed right-4 bottom-4 z-40 grid gap-2" aria-live="polite">
      {pending.map((f) => (
        <FormCard
          key={f.form_id}
          form={f}
          onAnswer={(action, content) => void answer(f.form_id, action, content)}
        />
      ))}
    </div>
  );
}
