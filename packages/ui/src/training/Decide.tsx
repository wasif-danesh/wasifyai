"use client";

import { gigabytes } from "@wasifyai/client";
import type {
  DecisionExample,
  DecisionKind,
  DecisionOption,
  DecisionSorted,
  Said,
  TrainedModel,
  TrainingApi,
  WritingRights,
} from "@wasifyai/client";
import { Plus, Trash2 } from "lucide-react";
import { type ReactNode, useId, useMemo, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Chip } from "../components/chip";
import { JobMeter, WorkingCard } from "../components/create";
import { Input } from "../components/input";
import { Notice } from "../components/notice";
import { Textarea } from "../components/textarea";
import { actions, chips, eyebrow, field, fieldLabel, hint, panel } from "../styles";
import { EvaluationLine } from "./CheckIt";
import { SetupCard } from "./SetupCard";
import { type DecideHook, useDecide } from "./use-decide";
import { useDecisionBases } from "./use-decision-bases";
import { useTrainingSetup } from "./use-setup";

const SELECT =
  "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30";

const RIGHTS: { id: WritingRights; label: string }[] = [
  { id: "mine", label: "They are mine" },
  { id: "permission", label: "I have permission to use them" },
];

const KINDS: { id: DecisionKind; label: string; note: string }[] = [
  { id: "yes_no", label: "Yes or no", note: "Is this review positive?" },
  { id: "category", label: "One of several", note: "Which team should handle this?" },
  { id: "score", label: "A score", note: "How urgent is this, from 1 to 5?" },
];

/** Examples shown for editing at once: more are kept, checked and used, but not drawn. */
const SHOWN = 40;

const sure = (c: number) => `${Math.round(c * 100)}%`;

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

// ---- a table of texts and answers, pasted or opened ---------------------------------------------

/** The cells of a table of text: tab separated (pasted from a spreadsheet) or comma or semicolon separated (a CSV file), with
 * quoted cells that may hold the separator, a line break or a doubled quote. */
export function parseCells(text: string): string[][] {
  const clean = text.replace(/^﻿/, "");
  const first = clean.split(/\r?\n/, 1)[0] ?? "";
  const count = (c: string) => first.split(c).length - 1;
  const sep = count("\t") > 0 ? "\t" : count(";") > count(",") ? ";" : ",";
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < clean.length; i++) {
    const c = clean[i];
    if (quoted) {
      if (c === '"' && clean[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (c === '"') {
        quoted = false;
      } else {
        cell += c;
      }
    } else if (c === '"' && cell === "") {
      quoted = true;
    } else if (c === sep) {
      row.push(cell);
      cell = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && clean[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += c;
    }
  }
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

const HEADERS = new Set([
  "answer",
  "label",
  "category",
  "class",
  "target",
  "sentiment",
  "score",
  "y",
  "result",
  "verdict",
  "decision",
]);

/** Texts and answers from a pasted or opened table: the first column is the text, the last is the answer; a first row that
 * names the columns ("text", "label") is left out. */
export function parseTable(text: string): DecisionExample[] {
  const rows = parseCells(text).filter((r) => r.length >= 2 && (r[0] ?? "").trim());
  const out = rows.map((r) => ({
    text: (r[0] ?? "").trim(),
    answer: (r[r.length - 1] ?? "").trim(),
  }));
  const head = out[0];
  if (head && HEADERS.has(head.answer.toLowerCase())) out.shift();
  return out.filter((r) => r.answer !== "");
}

// ---- the screen ---------------------------------------------------------------------------------

/**
 * "Teach it to decide" (ADR-0075): one question, texts with the right answers, a check in words, one button, and then
 * a report on texts it had not seen. Nothing here says encoder, loss or calibration: the person writes the question,
 * adds examples, checks and teaches.
 */
export function Decide({ api, pollMs }: { api: TrainingApi; pollMs?: number }) {
  const w = useDecide(api, pollMs);
  const { state } = w;
  const status = state.status;
  // the trainer's own component: offered while it is not there, read again once set up
  const setupApi = useMemo(
    () => ({
      setup: api.decisionSetup,
      installSetup: api.installDecisionSetup,
      cancelSetup: api.cancelDecisionSetup,
      removeSetup: api.removeDecisionSetup,
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
          intro="Teaching it to decide needs a trainer and a small model to learn on. They are not in the app. They are downloaded once, every file checked, and kept in the app's own folder. Nothing else on your computer is changed, and your texts are not sent anywhere."
        />
      ) : status && !status.ready ? (
        <Notice tone="warn" title="Teaching it to decide is not ready">
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

// ---- the sets -----------------------------------------------------------------------------------

function Sets({ w }: { w: DecideHook }) {
  const { state } = w;
  return (
    <section className={panel} aria-label="Sets of examples">
      <span className={eyebrow}>Decision model training</span>
      <h2 className="m-0 font-semibold text-lg">Teach it to decide</h2>
      <p className="m-0 max-w-3xl text-muted-foreground">
        Give it texts and the right answer to one question: yes or no, a category or a score. It
        learns to answer new texts the same way, and says how sure it is. It is taught on this
        computer: your texts are not sent anywhere.
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
                  · {s.question || "no question yet"} · {s.examples}{" "}
                  {s.examples === 1 ? "example" : "examples"}
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

// ---- the question -------------------------------------------------------------------------------

function QuestionStep({ w }: { w: DecideHook }) {
  const set = w.state.current;
  const status = w.state.status;
  const [options, setOptions] = useState<DecisionOption[]>(
    set && set.options.length > 0
      ? set.options
      : [
          { label: "", about: "" },
          { label: "", about: "" },
        ],
  );
  const questionId = useId();
  const levelsId = useId();
  const lowId = useId();
  const highId = useId();
  if (!set) return null;
  const [minLevels, maxLevels] = status?.levels ?? [3, 10, 5];
  const maxOptions = status?.max_options ?? 12;
  const saveOptions = (next: DecisionOption[]) => {
    setOptions(next);
    void w.patch({ options: next.filter((o) => o.label.trim() !== "") });
  };
  const edit = (i: number, change: Partial<DecisionOption>) =>
    setOptions(options.map((o, n) => (n === i ? { ...o, ...change } : o)));
  return (
    <div className="grid gap-3">
      <h2 className="m-0 font-semibold text-lg">1 The question</h2>
      <p className={hint}>
        What should it answer about every text? It gives one answer for each text.
      </p>
      <div className={field}>
        <label htmlFor={questionId} className={fieldLabel}>
          The question
        </label>
        <Input
          id={questionId}
          defaultValue={set.question}
          maxLength={300}
          placeholder="For example: Is this review positive?"
          onBlur={(e) => {
            if (e.target.value.trim() !== set.question)
              void w.patch({ question: e.target.value.trim() });
          }}
        />
      </div>
      <fieldset className={cn(field, "m-0 border-0 p-0")}>
        <legend className={cn(fieldLabel, "mb-1.5")}>The answer is</legend>
        <div className={chips}>
          {KINDS.map((k) => (
            <Chip
              key={k.id}
              aria-pressed={set.kind === k.id}
              onClick={() => void w.patch({ kind: k.id })}
            >
              {k.label}
            </Chip>
          ))}
        </div>
        <p className={hint}>{KINDS.find((k) => k.id === set.kind)?.note}</p>
      </fieldset>
      {set.kind === "category" ? (
        <fieldset className={cn(field, "m-0 border-0 p-0")}>
          <legend className={cn(fieldLabel, "mb-1.5")}>The categories</legend>
          <ul className="m-0 grid list-none gap-2 p-0">
            {options.map((o, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: options have no id and are edited in place
              <li key={i} className="grid gap-2 md:grid-cols-[1fr_2fr_auto]">
                <Input
                  value={o.label}
                  maxLength={60}
                  aria-label={`Name of category ${i + 1}`}
                  placeholder="Name, for example billing"
                  onChange={(e) => edit(i, { label: e.target.value })}
                  onBlur={() => saveOptions(options)}
                />
                <Input
                  value={o.about}
                  maxLength={200}
                  aria-label={`What category ${i + 1} means`}
                  placeholder="What it means (optional)"
                  onChange={(e) => edit(i, { about: e.target.value })}
                  onBlur={() => saveOptions(options)}
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  aria-label={`Remove category ${i + 1}`}
                  disabled={options.length <= 2}
                  onClick={() => saveOptions(options.filter((_, n) => n !== i))}
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
              size="sm"
              disabled={options.length >= maxOptions}
              onClick={() => setOptions([...options, { label: "", about: "" }])}
            >
              <Plus className="size-4" aria-hidden="true" /> Add a category
            </Button>
          </div>
          <p className={hint}>
            Say what each one means in a few words: it helps the model most when the names alone are
            not clear.
          </p>
        </fieldset>
      ) : null}
      {set.kind === "score" ? (
        <div className="grid gap-3 md:grid-cols-3">
          <div className={field}>
            <label htmlFor={levelsId} className={fieldLabel}>
              The score goes from 1 to
            </label>
            <Input
              id={levelsId}
              type="number"
              min={minLevels}
              max={maxLevels}
              defaultValue={set.levels}
              onBlur={(e) => {
                const n = Math.round(Number(e.target.value));
                if (n >= minLevels && n <= maxLevels && n !== set.levels)
                  void w.patch({ levels: n });
              }}
            />
          </div>
          <div className={field}>
            <label htmlFor={lowId} className={fieldLabel}>
              What 1 means
            </label>
            <Input
              id={lowId}
              defaultValue={set.low}
              maxLength={200}
              placeholder="For example: can wait"
              onBlur={(e) => void w.patch({ low: e.target.value.trim() })}
            />
          </div>
          <div className={field}>
            <label htmlFor={highId} className={fieldLabel}>
              What the top score means
            </label>
            <Input
              id={highId}
              defaultValue={set.high}
              maxLength={200}
              placeholder="For example: drop everything"
              onBlur={(e) => void w.patch({ high: e.target.value.trim() })}
            />
          </div>
        </div>
      ) : null}
      {set.problem ? <p className={hint}>{set.problem}</p> : null}
    </div>
  );
}

// ---- the examples -------------------------------------------------------------------------------

function ExamplesStep({ w }: { w: DecideHook }) {
  const { state } = w;
  const set = state.current;
  const [pasted, setPasted] = useState("");
  const [opened, setOpened] = useState<string | null>(null);
  const pasteId = useId();
  const fileId = useId();
  if (!set) return null;
  const rows = state.rows;
  const answers = set.answers ?? [];
  const change = (i: number, patch: Partial<DecisionExample>) =>
    w.setRows(rows.map((r, n) => (n === i ? { ...r, ...patch } : r)));
  const fromPaste = parseTable(pasted);
  const open = async (file: File | undefined) => {
    if (!file) return;
    const got = parseTable(await file.text());
    if (got.length === 0) {
      setOpened(`${file.name} has no rows with a text and an answer.`);
      return;
    }
    w.setRows([...rows, ...got]);
    setOpened(`Added ${got.length} ${got.length === 1 ? "row" : "rows"} from ${file.name}.`);
  };
  const shown = rows.slice(0, SHOWN);
  return (
    <div className="grid gap-3">
      <h2 className="m-0 font-semibold text-lg">2 Add examples</h2>
      <p className={hint}>
        A text, and the right answer for it. The more examples, the surer it gets:{" "}
        {state.status?.good_examples ?? 60} or more is a good start, with at least{" "}
        {state.status?.min_per_answer ?? 5} of each answer.
      </p>
      <ul className="m-0 grid list-none gap-3 p-0">
        {shown.map((r, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: rows have no id and are edited in place
          <li key={i} className="grid gap-2 rounded-xl border p-3 md:grid-cols-[2fr_1fr_auto]">
            <div className="grid gap-1 text-sm">
              <span className="font-medium">The text</span>
              <Textarea
                value={r.text}
                aria-label={`The text, example ${i + 1}`}
                onChange={(e) => change(i, { text: e.target.value })}
              />
            </div>
            <div className="grid content-start gap-1 text-sm">
              <span className="font-medium">The right answer</span>
              <select
                className={SELECT}
                value={r.answer}
                aria-label={`The right answer, example ${i + 1}`}
                onChange={(e) => change(i, { answer: e.target.value })}
              >
                <option value="">Choose…</option>
                {answers.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
                {r.answer && !answers.includes(r.answer) ? (
                  <option value={r.answer}>{r.answer} (not one of the answers)</option>
                ) : null}
              </select>
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
      {rows.length > SHOWN ? (
        <p className={hint}>
          And {rows.length - SHOWN} more {rows.length - SHOWN === 1 ? "example" : "examples"}. They
          are kept, checked and used; only the first {SHOWN} are shown for editing.
        </p>
      ) : null}
      <div className={actions}>
        <Button
          type="button"
          variant="outline"
          onClick={() => w.setRows([{ text: "", answer: "" }, ...rows])}
        >
          <Plus className="size-4" aria-hidden="true" /> Add an example
        </Button>
        {rows.length > 0 ? (
          <Sure label="Remove all" name="the examples" onSure={() => w.setRows([])} />
        ) : null}
        <span className="text-muted-foreground text-sm" aria-live="polite">
          {state.saving ? "Saving…" : rows.length > 0 && state.saved ? "Saved" : ""}
        </span>
      </div>
      <details className="rounded-lg border px-3 py-2">
        <summary className="cursor-pointer font-medium text-sm">
          Paste from a spreadsheet or open a file
        </summary>
        <div className="grid gap-3 pt-3">
          <label htmlFor={pasteId} className="text-sm">
            Two columns: the text, then the right answer. Copy them from your spreadsheet and paste
            them here.
          </label>
          <Textarea id={pasteId} value={pasted} onChange={(e) => setPasted(e.target.value)} />
          <div className={actions}>
            <Button
              type="button"
              size="sm"
              disabled={fromPaste.length === 0}
              onClick={() => {
                w.setRows([...rows, ...fromPaste]);
                setPasted("");
              }}
            >
              Add {fromPaste.length || ""} pasted {fromPaste.length === 1 ? "row" : "rows"}
            </Button>
          </div>
          <div className={field}>
            <label htmlFor={fileId} className="text-sm">
              Or open a file saved as CSV: the text in the first column and the right answer in the
              last.
            </label>
            <input
              id={fileId}
              type="file"
              accept=".csv,.tsv,.txt,text/csv,text/plain"
              className="w-full min-w-0 text-sm"
              onChange={(e) => {
                void open(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            {opened ? (
              <output className="text-muted-foreground text-sm" aria-live="polite">
                {opened}
              </output>
            ) : null}
          </div>
        </div>
      </details>
    </div>
  );
}

// ---- the model and the editor -------------------------------------------------------------------

/**
 * "Which model?": the models a decision model can be taught on. One that is not on this computer is chosen like the others
 * and fetched next to its name, after its size is shown; teaching waits for it.
 */
function ModelChoice({ w, api, pollMs }: { w: DecideHook; api: TrainingApi; pollMs?: number }) {
  const lang = useDecisionBases(api, pollMs, () => void w.replan());
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
                    onClick={() => void lang.cancel(b.id)}
                  >
                    Stop
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label={`Get ${b.title}`}
                    onClick={() => void lang.install(b.id, part.bytes)}
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
        Choose the one for many languages if your texts are not in English. Each is downloaded once,
        every file checked, and kept in the app's own folder.
      </p>
    </fieldset>
  );
}

/** What the collapsed "Choose the model and method" line says: the recommendation, or what was chosen. */
function chosenSummary(w: DecideHook): string {
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

function Editor({ w, api, pollMs }: { w: DecideHook; api: TrainingApi; pollMs?: number }) {
  const { state } = w;
  const set = state.current;
  const plan = state.plan;
  const nameId = useId();
  if (!set) return null;
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
      <span className={eyebrow}>Decision model training</span>
      <div className={field}>
        <label htmlFor={nameId} className={fieldLabel}>
          Name this set
        </label>
        <Input
          id={nameId}
          defaultValue={set.name}
          maxLength={60}
          placeholder="For example: Support messages"
          onBlur={(e) => {
            if (e.target.value.trim() !== set.name) void w.patch({ name: e.target.value.trim() });
          }}
        />
      </div>

      <QuestionStep key={set.id} w={w} />
      <ExamplesStep w={w} />

      <div className="grid gap-3">
        <h2 className="m-0 font-semibold text-lg">3 Check</h2>
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
            {Object.keys(plan.counts).length > 0 && plan.examples > 0 ? (
              <p className={hint}>
                {Object.entries(plan.counts)
                  .map(([a, n]) => `${a}: ${n}`)
                  .join(" · ")}
              </p>
            ) : null}
          </>
        ) : null}
        <fieldset className={cn(field, "m-0 border-0 p-0")}>
          <legend className={cn(fieldLabel, "mb-1.5")}>Whose are these texts?</legend>
          <div className={chips}>
            {RIGHTS.map((r) => (
              <Chip
                key={r.id}
                aria-pressed={set.rights === r.id}
                onClick={() => void w.patch({ rights: r.id })}
              >
                {r.label}
              </Chip>
            ))}
          </div>
          <p className={hint}>
            Use this to sort and flag things, not to decide about a person's job, credit or safety.
          </p>
        </fieldset>
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
                It is taught on {plan.base_title}: {plan.base_note} All of the model is taught, not
                a small adapter, so the result takes about 840 MB.
              </p>
            ) : null}
          </div>
        </details>
      </div>

      <div className="grid gap-2">
        <h2 className="m-0 font-semibold text-lg">4 Teach it</h2>
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

// ---- the run and its result ---------------------------------------------------------------------

function RunView({ w, api, onBack }: { w: DecideHook; api: TrainingApi; onBack: () => void }) {
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
        <DecideResult model={result} api={api} />
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

function Stat({
  label,
  right,
  of,
  percent,
  strong,
}: { label: string; right: number; of: number; percent: number; strong?: boolean }) {
  return (
    <div className={cn("grid gap-0.5 rounded-xl border p-3", strong && "border-primary")}>
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="font-semibold text-step-1">
        {right} of {of}
      </span>
      <span className="text-muted-foreground text-sm">{percent} percent right</span>
    </div>
  );
}

/** The answer and how sure the model is, with a bar for the second and a line for the other answers. */
function SaidView({
  said,
  title,
  quiet,
}: { said: Said; title: string; quiet?: boolean }): ReactNode {
  const others = Object.entries(said.shares)
    .filter(([a]) => a !== said.answer)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);
  return (
    <div className={cn("grid gap-1.5 rounded-lg p-3 text-sm", quiet ? "bg-muted" : "border")}>
      <span className="font-medium text-muted-foreground">{title}</span>
      <span className="text-base">
        <strong>{said.answer}</strong>{" "}
        <span className="text-muted-foreground">· {sure(said.confidence)} sure</span>
      </span>
      <span aria-hidden="true" className="block h-1.5 overflow-hidden rounded-full bg-border">
        <span className="block h-full bg-primary" style={{ width: sure(said.confidence) }} />
      </span>
      {others.length > 0 ? (
        <span className="text-muted-foreground">
          {others.map(([a, p]) => `${a} ${sure(p)}`).join(" · ")}
        </span>
      ) : null}
    </div>
  );
}

/** One text: what the taught model says, beside what the one it started from said. */
function TryOne({ model, api }: { model: TrainedModel; api: TrainingApi }) {
  const [text, setText] = useState("");
  const [asking, setAsking] = useState(false);
  const [got, setGot] = useState<{ mine: Said; original: Said | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const id = useId();
  const go = async () => {
    const t = text.trim();
    if (!t) return;
    setAsking(true);
    setError(null);
    try {
      const a = await api.askDecision(model.id, t);
      setGot({ mine: a.mine, original: a.original });
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "It could not decide.");
    } finally {
      setAsking(false);
    }
  };
  return (
    <section className="grid gap-2 rounded-xl border p-3" aria-label="Try it">
      <h3 className="m-0 font-semibold">Try it</h3>
      <div className={field}>
        <label htmlFor={id} className={fieldLabel}>
          Paste a text
        </label>
        <Textarea id={id} value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <div className={actions}>
        <Button type="button" disabled={asking || !text.trim()} onClick={() => void go()}>
          {asking ? "Deciding…" : "Decide"}
        </Button>
        <span className={hint}>The first answer takes a few seconds while the model loads.</span>
      </div>
      {error ? (
        <Notice tone="error" title="It could not decide">
          {error}
        </Notice>
      ) : null}
      {got ? (
        <div className="grid gap-2 md:grid-cols-2" aria-label="Its answer">
          {got.original ? (
            <SaidView said={got.original} title="Before it was taught" quiet />
          ) : null}
          <SaidView said={got.mine} title="Your model" />
        </div>
      ) : null}
    </section>
  );
}

const SORT_SHOWN = 50;

/** Many texts, one a line, each with its answer; the table can be copied into a spreadsheet. */
function SortList({ model, api }: { model: TrainedModel; api: TrainingApi }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [got, setGot] = useState<{ texts: string[]; sorted: DecisionSorted } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const id = useId();
  const texts = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const go = async () => {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      setGot({ texts, sorted: await api.sortDecision(model.id, texts) });
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "It could not decide.");
    } finally {
      setBusy(false);
    }
  };
  const copy = async () => {
    if (!got) return;
    const table = got.texts
      .map(
        (t, i) =>
          `${t}\t${got.sorted.results[i]?.answer ?? ""}\t${sure(got.sorted.results[i]?.confidence ?? 0)}`,
      )
      .join("\n");
    try {
      await navigator.clipboard.writeText(table);
      setCopied(true);
    } catch {
      setError("It could not be copied. Select the table and copy it.");
    }
  };
  return (
    <section className="grid gap-2 rounded-xl border p-3" aria-label="Sort a list">
      <h3 className="m-0 font-semibold">Sort a list</h3>
      <div className={field}>
        <label htmlFor={id} className={fieldLabel}>
          One text on each line
        </label>
        <Textarea id={id} value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <div className={actions}>
        <Button type="button" disabled={busy || texts.length === 0} onClick={() => void go()}>
          {busy
            ? "Deciding…"
            : `Decide ${texts.length || ""} ${texts.length === 1 ? "text" : "texts"}`}
        </Button>
      </div>
      {error ? (
        <Notice tone="error" title="It could not decide">
          {error}
        </Notice>
      ) : null}
      {got ? (
        <div className="grid gap-2">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">The answers</caption>
            <thead>
              <tr>
                <th className="pr-3">Text</th>
                <th className="pr-3">Answer</th>
                <th>Sure</th>
              </tr>
            </thead>
            <tbody>
              {got.texts.slice(0, SORT_SHOWN).map((t, i) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: the same text can be on two lines
                <tr key={i} className="border-t align-top">
                  <td className="py-1 pr-3">{t.length > 140 ? `${t.slice(0, 140)}…` : t}</td>
                  <td className="py-1 pr-3 font-medium">{got.sorted.results[i]?.answer}</td>
                  <td className="py-1">{sure(got.sorted.results[i]?.confidence ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {got.texts.length > SORT_SHOWN ? (
            <p className={hint}>
              The first {SORT_SHOWN} of {got.texts.length} are shown. Copy the table to get all of
              them.
            </p>
          ) : null}
          <div className={actions}>
            <Button type="button" variant="outline" size="sm" onClick={() => void copy()}>
              Copy as a table
            </Button>
            <span className="text-muted-foreground text-sm" aria-live="polite">
              {copied ? "Copied. Paste it into a spreadsheet." : ""}
            </span>
          </div>
        </div>
      ) : null}
    </section>
  );
}

/**
 * What was learnt, in words: the mark, how often it was right on texts kept back beside the same model before it was
 * taught and a plain word counter, where it went wrong and whether its confidence can be trusted (ADR-0075 decision 6),
 * then boxes to try it. Used after a run and under "My models".
 */
export function DecideResult({ model, api }: { model: TrainedModel; api: TrainingApi }) {
  const rep = model.card.report;
  const q = model.card.question;
  const peek = model.card.peek ?? [];
  return (
    <div className="grid gap-4">
      <h2 className="m-0 font-semibold text-lg">{model.name} is ready</h2>
      <EvaluationLine model={model} />
      {q ? (
        <p className={hint}>
          It answers: {q.text} {model.card.dataset.examples ?? 0} examples, {model.card.base_title}.
        </p>
      ) : null}
      {rep && rep.texts > 0 ? (
        <>
          <section className="grid gap-2 md:grid-cols-3" aria-label="How often it was right">
            <Stat
              label="After it was taught"
              right={rep.right.after}
              of={rep.texts}
              percent={rep.percent.after}
              strong
            />
            <Stat
              label="Before it was taught"
              right={rep.right.before}
              of={rep.texts}
              percent={rep.percent.before}
            />
            <Stat
              label="Counting words only"
              right={rep.right.word_counter}
              of={rep.texts}
              percent={rep.percent.word_counter}
            />
          </section>
          <p className={hint}>
            On {rep.texts} texts it had not seen while learning.
            {q?.kind === "score" ? " For a score, one level off counts as right." : ""}
          </p>
          <p className="m-0 text-sm">{rep.confidence.note}</p>
          {rep.per_answer.length > 0 ? (
            <section aria-label="Answer by answer" className="grid gap-1">
              <h3 className="m-0 font-semibold">Answer by answer</h3>
              <ul className="m-0 grid list-none gap-1 p-0 text-sm">
                {rep.per_answer.map((a) => (
                  <li key={a.answer}>
                    <strong>{a.answer}</strong>: right {a.right} of {a.of}
                  </li>
                ))}
              </ul>
              {rep.mix_ups.length > 0 ? (
                <p className={hint}>
                  It mixes up:{" "}
                  {rep.mix_ups
                    .map(
                      (m) =>
                        `${m.right} called ${m.said} (${m.times} ${m.times === 1 ? "time" : "times"})`,
                    )
                    .join(", ")}
                  .
                </p>
              ) : null}
            </section>
          ) : null}
          {rep.wrong.length > 0 ? (
            <details className="rounded-lg border px-3 py-2">
              <summary className="cursor-pointer font-medium text-sm">
                See {rep.wrong.length === 1 ? "the text" : `the ${rep.wrong.length} texts`} it got
                wrong
              </summary>
              <ul className="m-0 grid list-none gap-2 p-0 pt-3 text-sm">
                {rep.wrong.map((x) => (
                  <li key={x.text} className="grid gap-0.5 rounded-lg border p-2">
                    <span>{x.text}</span>
                    <span className="text-muted-foreground">
                      Right answer: {x.right}. It said {x.said}, {sure(x.confidence)} sure.
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      ) : null}
      {peek.length > 0 ? (
        <details className="rounded-lg border px-3 py-2">
          <summary className="cursor-pointer font-medium text-sm">
            The same texts, before and after
          </summary>
          <ul className="m-0 grid list-none gap-3 p-0 pt-3">
            {peek.map((p) => (
              <li key={p.text} className="grid gap-2 rounded-xl border p-3">
                <strong>{p.text.length > 200 ? `${p.text.slice(0, 200)}…` : p.text}</strong>
                <div className="grid gap-2 md:grid-cols-2">
                  <SaidView said={p.before} title="Before" quiet />
                  <SaidView said={p.after} title="After" />
                </div>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <TryOne model={model} api={api} />
      <SortList model={model} api={api} />
    </div>
  );
}
