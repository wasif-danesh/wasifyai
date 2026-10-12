"use client";

import { type FormState, submitModel } from "@/app/(site)/admin/models/actions";
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

import type { ModelView, ProviderView } from "@wasifyai/contracts";
import { useActionState, useId, useState } from "react";

const IDLE: FormState = { status: "idle" };

/** Change what serves one model alias. The API key box is write-only and always starts empty. */
export function ModelForm({
  model,
  providers,
}: {
  model: ModelView;
  providers: ProviderView[];
}) {
  const id = useId();
  const [state, action, pending] = useActionState(submitModel.bind(null, model.alias), IDLE);
  const [providerId, setProviderId] = useState(model.provider ?? providers[0]?.id ?? "");
  const provider = providers.find((p) => p.id === providerId);
  const showBase = provider?.needs_base || providerId === "openai_compatible";
  const showKey = provider ? provider.needs_key || providerId === "openai_compatible" : true;

  return (
    <form action={action} className={cn(panel, "gap-6")} aria-busy={pending}>
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor={`${id}-provider`}>Provider</FieldLabel>
          <Select name="provider" value={providerId} onValueChange={setProviderId}>
            <SelectTrigger id={`${id}-provider`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {providers.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel htmlFor={`${id}-model`}>Model</FieldLabel>
          <Input
            id={`${id}-model`}
            name="model"
            required
            maxLength={200}
            defaultValue={model.provider === providerId ? (model.model ?? "") : ""}
            placeholder={provider?.model_hint}
            key={providerId}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        {showBase ? (
          <Field>
            <FieldLabel htmlFor={`${id}-base`}>Server address</FieldLabel>
            <Input
              id={`${id}-base`}
              name="api_base"
              required={provider?.needs_base}
              maxLength={300}
              defaultValue={model.provider === providerId ? (model.api_base ?? "") : ""}
              placeholder="http://host.containers.internal:11434"
              key={`base-${providerId}`}
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
        ) : null}
        {showKey ? (
          <Field>
            <FieldLabel htmlFor={`${id}-key`}>API key</FieldLabel>
            <Input
              id={`${id}-key`}
              name="api_key"
              type="password"
              maxLength={512}
              autoComplete="off"
              spellCheck={false}
              aria-describedby={`${id}-key-hint`}
              placeholder={model.key_set ? "A key is saved. Enter it again to save changes." : ""}
            />
            <FieldDescription id={`${id}-key-hint`}>
              Keys are sent once, stored encrypted by the model gateway, and never shown again.
              {providerId === "openai_compatible" ? " Leave empty for a server without a key." : ""}
            </FieldDescription>
          </Field>
        ) : null}
      </FieldGroup>

      {model.protected ? (
        <p className="text-muted-foreground">
          This model decides what the guardrail allows. Saving runs the guardrail test cases on the
          new model first and only changes it if every must-refuse case is refused. It takes about a
          minute.
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2.5">
        <Button variant="outline" type="submit" name="intent" value="test" disabled={pending}>
          Test connection
        </Button>
        <Button type="submit" name="intent" value="save" disabled={pending}>
          {pending ? "Working…" : "Save"}
        </Button>
        {model.source === "custom" ? (
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

function Result({ state }: { state: FormState }) {
  switch (state.status) {
    case "tested":
      return state.outcome.ok ? (
        <Notice tone="ok" title="The connection works">
          It answered in {state.outcome.latency_ms} ms
          {state.outcome.sample ? `: “${state.outcome.sample}”` : ""}. Nothing is saved yet.
        </Notice>
      ) : (
        <Notice tone="error" title="It did not work">
          {state.outcome.error || "There was no answer."}
        </Notice>
      );
    case "saved":
      return (
        <Notice tone="ok" title="Saved">
          {state.checks === "passed" ? "It passed the guardrail test cases. " : ""}New requests use
          it right away.
        </Notice>
      );
    case "reset":
      return (
        <Notice tone="ok" title="Back to the default">
          New requests use the default model again.
        </Notice>
      );
    case "rejected":
      return (
        <Notice tone="error" title="Not saved: the new model did not pass the checks">
          {state.failures.length ? state.failures.join(" · ") : state.message}
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
