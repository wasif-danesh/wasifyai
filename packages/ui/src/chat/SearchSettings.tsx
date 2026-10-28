"use client";
// Web search settings (ADR-0083, stage CO3): which search service the assistant uses, whether the person allowed it, and the
// keys of the services that need one. A key is typed once and never shown again, only whether one is saved.
import type { AssistantApi, SearchProvider, SearchStatus } from "@wasifyai/client";
import { useEffect, useId, useState } from "react";
import { Button } from "../components/button";

export type SearchSettingsProps = {
  assistant: Pick<AssistantApi, "searchStatus" | "updateSearch">;
  /** this computer (the desktop's Settings), or a service (the web's Admin > Search: the admin's choice for everyone) */
  place?: "device" | "service";
};

function problem(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "That could not be saved.";
}

function ProviderKey({
  provider,
  onSave,
  onRemove,
  canSave,
  place,
}: {
  place: "device" | "service";
  provider: SearchProvider;
  onSave: (value: string) => Promise<void>;
  onRemove: () => Promise<void>;
  canSave: boolean;
}) {
  const id = useId();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setValue("");
    } catch (e) {
      setError(problem(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="grid gap-2">
      <label htmlFor={id} className="text-sm">
        {provider.title} key {provider.key_set ? "(saved)" : "(not saved yet)"}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <input
          id={id}
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          disabled={!canSave}
          placeholder={provider.key_set ? "Type a new key to replace it" : "Paste your key"}
          onChange={(e) => setValue(e.target.value)}
          className="h-9 min-w-0 flex-1 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        />
        <Button
          type="button"
          variant="outline"
          disabled={busy || !canSave || !value.trim()}
          onClick={() => void run(() => onSave(value))}
        >
          Save key
        </Button>
        {provider.key_set ? (
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => void run(onRemove)}
          >
            Remove key
          </Button>
        ) : null}
      </div>
      <p className="text-muted-foreground text-xs">
        {provider.note}{" "}
        {provider.key_url ? (
          <a
            href={provider.key_url}
            target="_blank"
            rel="noopener noreferrer"
            data-external=""
            className="underline underline-offset-4"
          >
            Get a key
          </a>
        ) : null}
      </p>
      {!canSave ? (
        <p className="text-muted-foreground text-xs">
          {place === "device"
            ? "Keys cannot be saved on this computer."
            : "Keys cannot be saved yet: the service has no key to keep them encrypted (MEDIA_SECRETS_KEY)."}
        </p>
      ) : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </div>
  );
}

export function SearchSettings({ assistant, place = "device" }: SearchSettingsProps) {
  const [status, setStatus] = useState<SearchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let gone = false;
    assistant
      .searchStatus()
      .then((s) => !gone && setStatus(s))
      .catch(() => !gone && setUnavailable(true));
    return () => {
      gone = true;
    };
  }, [assistant]);
  if (unavailable || !status) return null;

  async function update(change: Parameters<AssistantApi["updateSearch"]>[0]) {
    setStatus(await assistant.updateSearch(change));
  }
  const chosen = status.providers.find((p) => p.id === status.provider);
  return (
    <section className="grid gap-3" aria-label="Searching the web">
      <h3 className="m-0 font-semibold text-base">Searching the web</h3>
      <p className="text-muted-foreground text-sm">
        {place === "device"
          ? "The Search button in the chat box lets the assistant look things up on the internet. It is off until you allow it. What you ask is sent to the search service you choose, and the pages it reads are fetched from the internet by this computer. Nothing it finds is trusted: it cannot make or change anything because a web page said so."
          : "The Search button in the chat box lets the assistant look things up on the internet. You choose the search service and keep its key for everyone; each person allows searching for themself, and until they do nothing is sent. What a person asks is sent to the service, and the pages it reads are fetched by this service. Nothing it finds is trusted: it cannot make or change anything because a web page said so."}
      </p>
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm">Search service</legend>
        {status.providers.map((p) => (
          <label key={p.id} className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              name="search-service"
              className="mt-1"
              checked={p.id === status.provider}
              onChange={() => {
                setError(null);
                update({ provider: p.id }).catch((e) => setError(problem(e)));
              }}
            />
            <span>
              {p.title}
              <span className="block text-muted-foreground text-xs">
                {p.needs_key ? (p.key_set ? "Your key is saved. " : "Needs your key. ") : null}
                Sends your question to {p.sends_to}.
              </span>
            </span>
          </label>
        ))}
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={status.consented}
          onChange={(e) => {
            setError(null);
            update({ consent: e.target.checked }).catch((err) => setError(problem(err)));
          }}
        />
        {place === "device" ? "Allow" : "I allow"} searching the web with{" "}
        {chosen?.title ?? "this service"}
      </label>
      <p className="text-muted-foreground text-xs">{status.consent_text}</p>
      {chosen?.needs_key ? (
        <ProviderKey
          key={chosen.id}
          provider={chosen}
          canSave={status.can_save_keys}
          place={place}
          onSave={(value) => update({ key: { provider: chosen.id, value } })}
          onRemove={() => update({ remove_key: chosen.id })}
        />
      ) : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </section>
  );
}
