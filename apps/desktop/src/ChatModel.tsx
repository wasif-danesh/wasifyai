// SPDX-License-Identifier: AGPL-3.0-only
import { Button, Notice, cn } from "@wasifyai/ui";
import { useCallback, useEffect, useState } from "react";
import { FitBadge } from "./FitBadge";
import { languageApi } from "./api";
import { humanBytes } from "./engine";
import { type LanguageState, contextLabel } from "./language";

/** Which model answers (the assistant, Enhance): the chosen one, what else can be chosen, and a try-it.
 * Found files need the language engine (Settings); a running Ollama or LM Studio is used as it is. */
export function ChatModel() {
  const [state, setState] = useState<LanguageState | null>(null);
  const [context, setContext] = useState(8192);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<{ text: string; seconds: number; model: string } | null>(
    null,
  );
  const [question, setQuestion] = useState("Say hello in one short sentence.");

  const refresh = useCallback(async () => {
    try {
      const s = await languageApi.state();
      setState(s);
      if (s.selected) setContext(s.selected.context);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The list could not be read.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function run(job: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await job();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  if (!state)
    return error ? (
      <Notice tone="error" title="That did not work">
        {error}
      </Notice>
    ) : null;

  const choices = state.files.filter((f) => f.state !== "unsupported");
  const chosen = state.selected;
  return (
    <section className="grid gap-4" aria-label="Chat model">
      <div>
        <h2 className="font-semibold text-lg">Chat model</h2>
        <p className="text-muted-foreground text-sm">
          The model that answers when the app needs words: improving a prompt now, the assistant
          next.
        </p>
      </div>

      {error ? (
        <Notice tone="error" title="That did not work">
          {error}
        </Notice>
      ) : null}

      {chosen ? (
        <div className="grid gap-3 rounded-lg border p-4">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-medium">{chosen.name}</span>
            <span className="rounded-full border border-ok/40 px-2 py-0.5 text-ok text-xs">
              Chosen
            </span>
            <span className="text-muted-foreground text-xs">
              {chosen.kind === "file" ? "runs in the app's engine" : "runs in the other tool"}
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="ms-auto"
              disabled={busy}
              onClick={() => void run(() => languageApi.choose({ clear: true }))}
            >
              Choose none
            </Button>
          </div>
          {chosen.note ? (
            <Notice tone="warn" title="Answers may look odd">
              {chosen.note}
            </Notice>
          ) : null}
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => setAnswer(await languageApi.tryIt(question)));
            }}
          >
            <label className="sr-only" htmlFor="try-it">
              Try the model
            </label>
            <input
              id="try-it"
              className="h-9 min-w-0 flex-1 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
            <Button type="submit" size="sm" disabled={busy || !question.trim()}>
              {busy ? "Thinking…" : "Try it"}
            </Button>
          </form>
          {answer ? (
            <p className="text-sm">
              {answer.text || "(no words came back)"}{" "}
              <span className="text-muted-foreground text-xs">
                {answer.seconds} s, {answer.model}
              </span>
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">
          No model is chosen. Pick one below
          {state.engine.installed ? "." : ", after setting up the language engine in Settings."}
        </p>
      )}

      <label className="flex flex-wrap items-center gap-2 text-sm">
        <span>Context length</span>
        <select
          className="h-8 rounded-md border border-input bg-transparent px-2 text-sm"
          value={context}
          onChange={(e) => setContext(Number(e.target.value))}
        >
          {state.contexts.map((c) => (
            <option key={c} value={c}>
              {contextLabel(c)} tokens
            </option>
          ))}
        </select>
        <span className="text-muted-foreground text-xs">
          Longer remembers more and needs more memory; the badges below follow it.
        </span>
      </label>

      <ul className="grid gap-2">
        {choices.map((f) => (
          <li key={f.id} className="grid gap-1 rounded-lg border p-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="min-w-0 flex-1 truncate font-medium" title={f.path}>
                {f.name}
              </span>
              <span className="text-muted-foreground text-xs">{humanBytes(f.size)}</span>
              {f.fit ? <FitBadge fit={f.fit} /> : null}
              {f.chosen ? (
                <span className="text-ok text-xs">Chosen</span>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  disabled={busy || f.state !== "can_use"}
                  onClick={() => void run(() => languageApi.choose({ item_id: f.id, context }))}
                >
                  Use for chat
                </Button>
              )}
            </div>
            <p className={cn("text-xs", f.state === "can_use" ? "text-muted-foreground" : "")}>
              Found in {f.tool_title}
              {f.quant ? ` · ${f.quant}` : ""} · {f.reason}
            </p>
          </li>
        ))}
        {state.servers.map((s) => (
          <li
            key={`${s.url}/${s.model}`}
            className="flex flex-wrap items-center gap-3 rounded-lg border p-3"
          >
            <span className="min-w-0 flex-1 truncate font-medium">{s.model}</span>
            <span className="text-muted-foreground text-xs">running in {s.title}</span>
            {s.chosen ? (
              <span className="text-ok text-xs">Chosen</span>
            ) : (
              <Button
                type="button"
                size="sm"
                disabled={busy}
                onClick={() =>
                  void run(() =>
                    languageApi.choose({
                      server: { tool: s.tool, url: s.url, model: s.model },
                      context,
                    }),
                  )
                }
              >
                Use for chat
              </Button>
            )}
          </li>
        ))}
      </ul>
      {choices.length === 0 && state.servers.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No language models were found on this computer yet. The model hub will let you get one.
        </p>
      ) : null}
    </section>
  );
}
