"use client";

import { type MediaFormState, submitMedia } from "@/app/(site)/admin/media/actions";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { panel } from "@/lib/styles";
import { cn } from "@/lib/utils";

import type { MediaBackend, MediaView } from "@wasifyai/contracts";
import { useActionState, useId, useState } from "react";

const IDLE: MediaFormState = { status: "idle" };

/** Choose what runs one media capability. The API key box is write-only and always starts empty. */
/** A row that has a key saved, offered as "Use the key saved for …" to rows on the same service. */
export type KeyRow = { id: string; backend: string; label: string };

export function MediaForm({
  item,
  backends,
  secretsReady,
  keyRows = [],
}: {
  item: MediaView;
  backends: MediaBackend[];
  secretsReady: boolean;
  keyRows?: KeyRow[];
}) {
  const id = useId();
  const allowed = backends.filter((b) => item.allowed_backends.includes(b.id));
  const [state, action, pending] = useActionState(
    submitMedia.bind(null, item.product_id, item.capability),
    IDLE,
  );
  const [backendId, setBackendId] = useState(item.backend);
  const backend = allowed.find((b) => b.id === backendId) ?? allowed[0];
  const same = backend?.id === item.backend;
  const secret = backend?.fields.find((f) => f.secret);
  const borrowable = keyRows.filter((r) => r.backend === backend?.id);
  const [keyFrom, setKeyFrom] = useState("");

  return (
    <form action={action} className={cn(panel, "gap-6")} aria-busy={pending}>
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor={`${id}-backend`}>Runs on</FieldLabel>
          <Select name="backend" value={backend?.id} onValueChange={setBackendId}>
            <SelectTrigger id={`${id}-backend`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {allowed.map((b) => (
                <SelectItem key={b.id} value={b.id}>
                  {b.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {backend ? <FieldDescription>{backend.description}</FieldDescription> : null}
        </Field>

        {backend?.fields
          .filter((f) => !f.secret)
          .map((f) => (
            <Field key={`${backend.id}-${f.name}`}>
              <FieldLabel htmlFor={`${id}-${f.name}`}>
                {f.label}
                {f.required ? "" : " (optional)"}
              </FieldLabel>
              <Input
                id={`${id}-${f.name}`}
                name={`cfg_${f.name}`}
                required={f.required}
                maxLength={300}
                defaultValue={same ? (item.config[f.name] ?? "") : ""}
                placeholder={f.placeholder}
                autoComplete="off"
                spellCheck={false}
              />
              {f.help ? <FieldDescription>{f.help}</FieldDescription> : null}
            </Field>
          ))}

        {secret ? (
          <Field key={`${backend?.id}-key`}>
            <FieldLabel htmlFor={`${id}-key`}>
              {secret.label}
              {secret.required ? "" : " (optional)"}
            </FieldLabel>
            <Input
              id={`${id}-key`}
              name="api_key"
              type="password"
              maxLength={512}
              autoComplete="off"
              spellCheck={false}
              disabled={!secretsReady || keyFrom !== ""}
              aria-describedby={`${id}-key-hint`}
              placeholder={
                same && item.key_set
                  ? "A key is saved. Leave empty to keep it, or enter a new one."
                  : ""
              }
            />
            <FieldDescription id={`${id}-key-hint`}>
              {secretsReady
                ? "Sent once, stored encrypted, and never shown again."
                : "Saving keys is off: set MEDIA_SECRETS_KEY (run make setup) and restart."}
            </FieldDescription>
          </Field>
        ) : null}

        {secret && borrowable.length > 0 ? (
          <Field key={`${backend?.id}-key-from`}>
            <FieldLabel htmlFor={`${id}-key-from`}>Or use a key already saved</FieldLabel>
            <Select
              name="key_from"
              value={keyFrom || "none"}
              onValueChange={(v) => setKeyFrom(v === "none" ? "" : v)}
            >
              <SelectTrigger id={`${id}-key-from`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No, use the key above</SelectItem>
                {borrowable.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    Use the key saved for {r.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldDescription>
              The key is copied inside the service; it is never shown.
            </FieldDescription>
          </Field>
        ) : null}
      </FieldGroup>

      <div className="flex flex-wrap items-center gap-2.5">
        <Button variant="outline" type="submit" name="intent" value="test" disabled={pending}>
          Test connection
        </Button>
        <Button type="submit" name="intent" value="save" disabled={pending}>
          {pending ? "Working…" : "Save"}
        </Button>
        {item.source === "custom" ? (
          <Button
            variant="outline"
            type="submit"
            name="intent"
            value="reset"
            formNoValidate
            disabled={pending}
          >
            Reset to default
          </Button>
        ) : null}
      </div>
      <Result state={state} />
    </form>
  );
}

function Result({ state }: { state: MediaFormState }) {
  switch (state.status) {
    case "tested":
      return state.outcome.ok ? (
        <Notice tone="ok" title="The connection works">
          {state.outcome.message} ({state.outcome.latency_ms} ms). This only checks that the service
          answers; it does not make anything. Nothing is saved yet.
        </Notice>
      ) : (
        <Notice tone="error" title="It did not work">
          {state.outcome.message}
        </Notice>
      );
    case "saved":
      return (
        <Notice tone="ok" title="Saved">
          The next job uses it.
        </Notice>
      );
    case "reset":
      return (
        <Notice tone="ok" title="Back to the default">
          The next job runs on the default again: the product's own ComfyUI workflow, or the engine
          workers for speaking and 3D models.
        </Notice>
      );
    case "error":
      return (
        <Notice tone="error" title="Something went wrong">
          {state.message}
        </Notice>
      );
    default:
      return null;
  }
}
