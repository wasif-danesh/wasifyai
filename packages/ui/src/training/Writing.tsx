"use client";

import { gigabytes } from "@wasifyai/client";
import type { TrainedModel, TrainingApi, WritingAsk, WritingExample } from "@wasifyai/client";
import { Plus, Trash2 } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { JobMeter, WorkingCard } from "../components/create";
import { Input } from "../components/input";
import { Notice } from "../components/notice";
import { Textarea } from "../components/textarea";
import { actions, chips, field, fieldLabel, hint, panel } from "../styles";
import { EvaluationLine } from "./CheckIt";
import { SetupCard } from "./SetupCard";
import { useLanguageBases } from "./use-language-bases";
import { useTrainingSetup } from "./use-setup";
import { type WritingHook, useWriting } from "./use-writing";
import { useWritingChat } from "./use-writing-chat";

/** A button that asks once more before it removes something. */
function Sure({ label, name, onSure }: { label: string; name: string; onSure: () => void }) {
  const [asked, setAsked] = useState(false);
  return asked ? (
    <span className="flex items-center gap-2 text-sm">
      Remove {name}?
      <Button type="button" size="sm" variant="destructive" onClick={onSure}>
        Yes, {label.toLowerCase()}
      </Button>
      <Button type="button" size="sm" variant="outline" onClick={() => setAsked(false)}>
        No
      </Button>
    </span>
  ) : (
    <Button
      type="button"
      size="sm"
      variant="outline"
      aria-label={`${label} ${name}`}
      onClick={() => setAsked(true)}
    >
      {label}
    </Button>
  );
}

/**
 * "Teach it from examples" (ADR-0074): questions with the answers the person wants, a check in
 * words, one button, and then the same questions asked before and after, side by side. Nothing here says QLoRA, steps
 * or loss; the person types, checks and teaches.
 */
export function Writing({ api, pollMs }: { api: TrainingApi; pollMs?: number }) {
  const w = useWriting(api, pollMs);
  const { state } = w;
  const status = state.status;
  // the writing trainer's own component: offered while it is not there, read again once set up
  const setupApi = useMemo(
    () => ({
      setup: api.writingSetup,
      installSetup: api.installWritingSetup,
      cancelSetup: api.cancelWritingSetup,
      removeSetup: api.removeWritingSetup,
    }),
    [api],
  );
  const setup = useTrainingSetup(setupApi, true, () => void w.refresh(), pollMs);
  const offer = setup.setup;
  return (
    <div className="grid gap-5">
      {status && !status.ready && offer?.plan.supported && !offer.installed ? (
        <SetupCard
          setup={offer}
          error={setup.error}
          onInstall={(bytes) => void setup.install(bytes)}
          onCancel={() => void setup.cancel()}
          intro="Teaching a writing model needs a trainer and a small model to learn on. They are not in the app. They are downloaded once, every file checked, and kept in the app's own folder. Nothing else on your computer is changed, and your examples are not sent anywhere."
        />
      ) : status && !status.ready ? (
        <Notice tone="warn" title="Teaching a writing model is not ready">
          {offer?.problem ?? status.problem ?? "It could not be started."}
        </Notice>
      ) : null}
      {status?.fit?.verdict === "too_big" ? (
        <Notice tone="warn" title="Not enough memory to teach a model">
          {status.fit.reason}
        </Notice>
      ) : null}
      {state.error ? (
        <Notice tone="error" title="That did not work">
          {state.error}
        </Notice>
      ) : null}
      {state.loading ? (
        <output className="text-muted-foreground">Looking at your sets…</output>
      ) : state.run ? (
        <RunView w={w} api={api} onBack={() => void w.leave()} />
      ) : state.current ? (
        <Editor w={w} api={api} pollMs={pollMs} />
      ) : (
        <Sets w={w} />
      )}
    </div>
  );
}

// ---- the sets -------------------------------------------------------------------------------

function Sets({ w }: { w: WritingHook }) {
  const { state } = w;
  return (
    <section className={panel} aria-label="Sets of examples">
      <p className="m-0 max-w-3xl text-muted-foreground">
        Add questions and the answers you want. The app teaches a small model to answer that way, on
        this computer: your examples are not sent anywhere. It learns how to answer, not new facts.
      </p>
      <div className={actions}>
        <Button
          type="button"
          disabled={state.busy || state.status?.ready === false}
          onClick={() => void w.newSet()}
        >
          New set of examples
        </Button>
      </div>
      {state.sets.length > 0 ? (
        <ul className="m-0 grid list-none gap-2 p-0">
          {state.sets.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 rounded-xl border p-3">
              <span className="min-w-0 flex-1">
                <strong>{s.name || "Untitled set"}</strong>{" "}
                <span className="text-muted-foreground">
                  · {s.examples} {s.examples === 1 ? "example" : "examples"}
                </span>
              </span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                aria-label={`Continue ${s.name || "the set"}`}
                onClick={() => void w.openSet(s.id)}
              >
                Continue
              </Button>
              <Sure
                label="Remove"
                name={s.name || "the set"}
                onSure={() => void w.removeSet(s.id)}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

// ---- add examples, check, teach -------------------------------------------------------------

/** Rows from a pasted spreadsheet: one example a line, the question and the answer between a tab. */
export function parsePasted(text: string): WritingExample[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.split("\t"))
    .filter((cells) => cells.length >= 2 && cells[0]?.trim() && cells[1]?.trim())
    .map((cells) => ({ ask: (cells[0] ?? "").trim(), answer: cells.slice(1).join(" ").trim() }));
}

/**
 * "Which model?": the models a writing model can be taught on, with what each is good for and what a real run on this
 * Mac measured. One that is not on this computer is chosen like the others and fetched next to its name, after its
 * size is shown; teaching waits for it.
 */
function ModelChoice({ w, api, pollMs }: { w: WritingHook; api: TrainingApi; pollMs?: number }) {
  const lang = useLanguageBases(api, pollMs, () => void w.replan());
  const group = useId();
  const rows = w.state.status?.choices.bases ?? [];
  const chosen = w.state.current?.base || w.state.status?.choices.default_base || "";
  if (rows.length < 2) return null;
  return (
    <fieldset className={cn(field, "m-0 border-0 p-0")}>
      <legend className={cn(fieldLabel, "mb-1.5")}>Which model?</legend>
      <div className="grid gap-2">
        {rows.map((b) => {
          const part = lang.bases.find((x) => x.id === b.id)?.model;
          const getting = part?.progress.state === "installing";
          const value =
            part && part.progress.total_bytes > 0
              ? part.progress.done_bytes / part.progress.total_bytes
              : undefined;
          return (
            <div
              key={b.id}
              className="flex items-start gap-3 rounded-lg border px-3 py-2 has-[:checked]:border-primary"
            >
              <input
                type="radio"
                name={group}
                className="mt-1"
                aria-label={b.title}
                checked={chosen === b.id}
                disabled={!b.can_teach}
                onChange={() => void w.patch({ base: b.id })}
              />
              <span className="grid min-w-0 flex-1 gap-0.5">
                <span>
                  {b.title}
                  {b.recommended ? (
                    <span className="ml-2 rounded-full border px-2 py-0.5 text-xs">
                      Recommended
                    </span>
                  ) : null}
                </span>
                <span className={hint}>
                  {b.can_teach ? b.note : b.reason}
                  {b.measured ? ` Measured here: ${b.measured}.` : ""}
                </span>
                {getting ? (
                  <JobMeter
                    title="Getting the model"
                    text={value === undefined ? "Starting" : `${Math.round(value * 100)}%`}
                    value={value}
                    label={`Download progress of ${b.title}`}
                  />
                ) : null}
                {part?.progress.state === "failed" ? (
                  <span className="text-destructive text-sm">{part.progress.message}</span>
                ) : null}
              </span>
              {b.can_teach && !b.installed && part ? (
                getting ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label={`Stop getting ${b.title}`}
                    onClick={() => void lang.cancel(b.id, "model")}
                  >
                    Stop
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label={`Get ${b.title}`}
                    onClick={() => void lang.install(b.id, "model", part.bytes)}
                  >
                    Get it ({gigabytes(part.bytes)})
                  </Button>
                )
              ) : null}
            </div>
          );
        })}
      </div>
      {lang.error ? <span className="text-destructive text-sm">{lang.error}</span> : null}
      <p className={hint}>
        A larger model follows your examples more closely and takes longer to teach. Each is
        downloaded once, every file checked, and kept in the app's own folder.
      </p>
    </fieldset>
  );
}

/** What the collapsed "Choose the model and method" line says: the recommendation, or what was chosen. */
function chosenSummary(w: WritingHook): string {
  const set = w.state.current;
  const rows = w.state.status?.choices.bases ?? [];
  const base = set?.base || w.state.status?.choices.default_base || "";
  const picked = rows.find((b) => b.id === base);
  const changed =
    (set?.base && set.base !== w.state.status?.choices.default_base) || set?.quality === "better";
  return changed
    ? `${picked?.title ?? w.state.plan?.base_title ?? ""}, ${set?.quality === "better" ? "Better" : "Quick"}`
    : "Recommended";
}

function Editor({ w, api, pollMs }: { w: WritingHook; api: TrainingApi; pollMs?: number }) {
  const { state } = w;
  const set = state.current;
  const plan = state.plan;
  const [pasted, setPasted] = useState("");
  const nameId = useId();
  const pasteId = useId();
  if (!set) return null;
  const rows = state.rows;
  const change = (i: number, patch: Partial<WritingExample>) =>
    w.setRows(rows.map((r, n) => (n === i ? { ...r, ...patch } : r)));
  const status = state.status;
  const blocked =
    state.busy ||
    status?.busy === true ||
    status?.ready === false ||
    status?.fit?.verdict === "too_big" ||
    plan === null ||
    plan.missing !== null;
  return (
    <section className={panel} aria-label="Examples">
      <div className={field}>
        <label htmlFor={nameId} className={fieldLabel}>
          Name this set
        </label>
        <Input
          id={nameId}
          defaultValue={set.name}
          maxLength={60}
          placeholder="For example: Customer replies"
          onBlur={(e) => {
            if (e.target.value.trim() !== set.name) void w.patch({ name: e.target.value.trim() });
          }}
        />
      </div>

      <div className="grid gap-3">
        <h2 className="m-0 font-semibold text-lg">1 Add examples</h2>
        <p className={hint}>
          A question, and the answer you want. The more examples, the better: 50 or more is a good
          start.
        </p>
        <ul className="m-0 grid list-none gap-3 p-0">
          {rows.map((r, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: rows have no id and are edited in place
            <li key={i} className="grid gap-2 rounded-xl border p-3 md:grid-cols-[1fr_1fr_auto]">
              <div className="grid gap-1 text-sm">
                <span className="font-medium">What it is asked</span>
                <Textarea
                  value={r.ask}
                  aria-label={`What it is asked, example ${i + 1}`}
                  onChange={(e) => change(i, { ask: e.target.value })}
                />
              </div>
              <div className="grid gap-1 text-sm">
                <span className="font-medium">What it should answer</span>
                <Textarea
                  value={r.answer}
                  aria-label={`What it should answer, example ${i + 1}`}
                  onChange={(e) => change(i, { answer: e.target.value })}
                />
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                aria-label={`Remove example ${i + 1}`}
                onClick={() => w.setRows(rows.filter((_, n) => n !== i))}
              >
                <Trash2 className="size-4" aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
        <div className={actions}>
          <Button
            type="button"
            variant="outline"
            onClick={() => w.setRows([...rows, { ask: "", answer: "" }])}
          >
            <Plus className="size-4" aria-hidden="true" /> Add an example
          </Button>
          <span className="text-muted-foreground text-sm" aria-live="polite">
            {state.saving ? "Saving…" : rows.length > 0 && state.saved ? "Saved" : ""}
          </span>
        </div>
        <details className="rounded-lg border px-3 py-2">
          <summary className="cursor-pointer font-medium text-sm">Paste from a spreadsheet</summary>
          <div className="grid gap-2 pt-3">
            <label htmlFor={pasteId} className="text-sm">
              Two columns: the question, then the answer. Copy them from your spreadsheet and paste
              them here.
            </label>
            <Textarea id={pasteId} value={pasted} onChange={(e) => setPasted(e.target.value)} />
            <div className={actions}>
              <Button
                type="button"
                size="sm"
                disabled={parsePasted(pasted).length === 0}
                onClick={() => {
                  w.setRows([...rows, ...parsePasted(pasted)]);
                  setPasted("");
                }}
              >
                Add {parsePasted(pasted).length || ""} pasted{" "}
                {parsePasted(pasted).length === 1 ? "row" : "rows"}
              </Button>
            </div>
          </div>
        </details>
      </div>

      <div className="grid gap-3">
        <h2 className="m-0 font-semibold text-lg">2 Check</h2>
        {plan ? (
          <>
            {plan.dropped.map((d) => (
              <Notice key={d} tone="info" title="Left out">
                {d}
              </Notice>
            ))}
            {plan.checks.map((c) => (
              <Notice
                key={c.code}
                tone={c.level === "error" ? "error" : c.level === "warn" ? "warn" : "info"}
                title={
                  c.level === "ok" ? "Ready" : c.level === "warn" ? "Before you start" : "Not yet"
                }
              >
                {c.message}
              </Notice>
            ))}
          </>
        ) : null}
        <details className="rounded-lg border px-3 py-2">
          <summary className="cursor-pointer font-semibold">
            Choose the model and method
            <span className="ml-2 font-normal text-muted-foreground">{chosenSummary(w)}</span>
          </summary>
          <div className="mt-3 grid gap-4">
            <fieldset className={cn(field, "m-0 border-0 p-0")}>
              <legend className={cn(fieldLabel, "mb-1.5")}>How careful?</legend>
              <div className={chips}>
                <Chip
                  aria-pressed={set.quality === "quick"}
                  onClick={() => void w.patch({ quality: "quick" })}
                >
                  Quick
                </Chip>
                <Chip
                  aria-pressed={set.quality === "better"}
                  onClick={() => void w.patch({ quality: "better" })}
                >
                  Better
                </Chip>
              </div>
              <p className={hint}>
                Better goes over your examples twice as often and takes about twice as long.
              </p>
            </fieldset>
            <ModelChoice w={w} api={api} pollMs={pollMs} />
            {plan ? (
              <p className={hint}>
                It is taught on {plan.base_title}: {plan.base_note}
              </p>
            ) : null}
          </div>
        </details>
      </div>

      <div className="grid gap-2">
        <h2 className="m-0 font-semibold text-lg">3 Teach it</h2>
        <div className={actions}>
          <Button type="button" size="lg" disabled={blocked} onClick={() => void w.teach()}>
            Teach it
          </Button>
          <Button type="button" variant="outline" onClick={() => void w.leave()}>
            Back
          </Button>
          <span className="text-muted-foreground">
            {plan?.missing ??
              `${plan?.estimate ?? ""}. Chat and image making pause while it learns.`}
          </span>
        </div>
      </div>
    </section>
  );
}

// ---- the run and its result -----------------------------------------------------------------

function RunView({ w, api, onBack }: { w: WritingHook; api: TrainingApi; onBack: () => void }) {
  const run = w.state.run;
  if (!run) return null;
  if (run.status === "working") {
    return (
      <section className={panel} aria-label="The run">
        <WorkingCard label="Teaching" onCancel={() => void w.stop()}>
          <JobMeter
            title="Teaching the model"
            text={`${Math.round(run.progress * 100)}%`}
            value={run.progress}
            label="Teaching progress"
          />
          <p className={hint}>
            {run.stage || "Starting"}. {run.estimate} in all.
          </p>
        </WorkingCard>
      </section>
    );
  }
  const result = w.state.result;
  return (
    <section className={panel} aria-label="The result">
      {run.status === "done" && result ? (
        <WritingResult model={result} api={api} />
      ) : run.status === "done" ? (
        <output className="text-muted-foreground">Getting what it learnt…</output>
      ) : (
        <Notice
          tone={run.status === "cancelled" ? "info" : "error"}
          title={run.status === "cancelled" ? "Stopped" : "It did not finish"}
        >
          {run.error || "It stopped. Nothing was kept."}
        </Notice>
      )}
      <div className={actions}>
        <Button type="button" variant="outline" onClick={onBack}>
          Back to my sets
        </Button>
      </div>
    </section>
  );
}

/**
 * "Chat with it": the taught model answers in chat, served by the app's own language engine on its base. The first
 * time the app needs the base in the form that engine runs (a download, with its size shown before anything is
 * fetched); afterwards one button to use it and one to go back to the model chosen before.
 */
export function ChatWithIt({
  model,
  api,
  pollMs,
}: { model: TrainedModel; api: TrainingApi; pollMs?: number }) {
  const c = useWritingChat(api, model.id, model.base, pollMs);
  const copy = c.copy;
  const downloading = copy?.progress.state === "installing";
  const value =
    copy && copy.progress.total_bytes > 0
      ? copy.progress.done_bytes / copy.progress.total_bytes
      : undefined;
  if (!c.canChat) return null; // the chat engine is not this computer's: nothing to offer here
  return (
    <section className="grid gap-2 rounded-xl border p-3" aria-label="Chat with it">
      <h3 className="m-0 font-semibold">Chat with it</h3>
      {c.mine ? (
        <>
          <p className="m-0 text-sm">
            Chat answers with this model now. The model you chose before is waiting.
          </p>
          <div className={actions}>
            <Button type="button" variant="outline" disabled={c.busy} onClick={() => void c.stop()}>
              Back to my chat model
            </Button>
          </div>
        </>
      ) : copy === null ? null : copy.have ? (
        <div className={actions}>
          <Button type="button" disabled={c.busy} onClick={() => void c.use()}>
            {c.inChat ? "Use this one in chat instead" : "Use in chat"}
          </Button>
          <span className={hint}>It learns how to answer, not new facts.</span>
        </div>
      ) : downloading ? (
        <WorkingCard
          label={copy.progress.message || "Downloading"}
          onCancel={() => void c.cancel()}
        >
          <JobMeter
            title="Getting the model for chat"
            text={value === undefined ? "Starting" : `${Math.round(value * 100)}%`}
            value={value}
            label="Download progress"
          />
        </WorkingCard>
      ) : (
        <>
          <p className="m-0 text-sm">
            To chat with it, the app needs the same model in the form its chat engine runs:{" "}
            {copy.title}, {gigabytes(copy.bytes)}, from {c.base?.source}. It is downloaded once,
            every file checked, and kept in the app's own folder. You need about{" "}
            {gigabytes(copy.needs_free_bytes)} of free disk space.
          </p>
          <div className={actions}>
            <Button
              type="button"
              disabled={Boolean(c.base?.problem)}
              onClick={() => void c.download()}
            >
              Download ({gigabytes(copy.bytes)}) and use in chat
            </Button>
          </div>
          {c.base?.problem ? <p className={hint}>{c.base?.problem}</p> : null}
          {copy.progress.state === "failed" ? (
            <Notice tone="error" title="The download did not finish">
              {copy.progress.message}
            </Notice>
          ) : null}
        </>
      )}
      {c.error ? (
        <Notice tone="error" title="That did not work">
          {c.error}
        </Notice>
      ) : null}
    </section>
  );
}

/**
 * What was learnt, in words: the mark, the same questions answered before and after side by side, and a box to
 * ask both something new (ADR-0074 decision 7). Used after a run and under "My models".
 */
export function WritingResult({
  model,
  api,
  pollMs,
}: { model: TrainedModel; api: TrainingApi; pollMs?: number }) {
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [got, setGot] = useState<WritingAsk | null>(null);
  const [error, setError] = useState<string | null>(null);
  const askId = useId();
  const answers = model.card.answers ?? [];
  const ask = async () => {
    const q = question.trim();
    if (!q) return;
    setAsking(true);
    setError(null);
    try {
      setGot(await api.askWriting(model.id, q));
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "It could not answer.");
    } finally {
      setAsking(false);
    }
  };
  return (
    <div className="grid gap-4">
      <h2 className="m-0 font-semibold text-lg">{model.name} is ready</h2>
      <EvaluationLine model={model} />
      <p className={hint}>
        The same questions, asked before it learnt and after. {model.card.dataset.examples ?? 0}{" "}
        examples, {model.card.base_title}.
      </p>
      <ul className="m-0 grid list-none gap-3 p-0">
        {answers.map((a) => (
          <li key={a.question} className="grid gap-2 rounded-xl border p-3">
            <strong>{a.question}</strong>
            <div className="grid gap-2 md:grid-cols-2">
              <p className="m-0 rounded-lg bg-muted p-3 text-sm">
                <span className="mb-1 block font-medium text-muted-foreground">Before</span>
                {a.before}
              </p>
              <p className="m-0 rounded-lg border p-3 text-sm">
                <span className="mb-1 block font-medium text-muted-foreground">After</span>
                {a.after}
              </p>
            </div>
          </li>
        ))}
      </ul>
      <div className={field}>
        <label htmlFor={askId} className={fieldLabel}>
          Ask both something new
        </label>
        <div className="flex flex-wrap gap-2">
          <Input
            id={askId}
            className="min-w-60 flex-1"
            value={question}
            maxLength={2000}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void ask();
            }}
          />
          <Button type="button" disabled={asking || !question.trim()} onClick={() => void ask()}>
            {asking ? "Asking…" : "Ask both"}
          </Button>
        </div>
      </div>
      {error ? (
        <Notice tone="error" title="It could not answer">
          {error}
        </Notice>
      ) : null}
      <ChatWithIt model={model} api={api} pollMs={pollMs} />
      {got ? (
        <div className="grid gap-2 md:grid-cols-2" aria-label="Its answers">
          <p className="m-0 rounded-lg bg-muted p-3 text-sm">
            <span className="mb-1 block font-medium text-muted-foreground">The original</span>
            {got.original}
          </p>
          <p className="m-0 rounded-lg border p-3 text-sm">
            <span className="mb-1 block font-medium text-muted-foreground">Your model</span>
            {got.mine}
          </p>
        </div>
      ) : null}
    </div>
  );
}
