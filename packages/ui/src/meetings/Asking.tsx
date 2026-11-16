// Asking about a meeting (ADR-0108 decision 16, stage MT5): questions answered by a notebook the
// meeting is in, with the lines they came from; and "Add to a notebook", to ask across many.
import type { Meeting, MeetingQuestion, MeetingsApi } from "@wasifyai/client";
import { BookPlus, MessageCircleQuestion, Square, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useId, useState } from "react";
import { Markdown } from "../chat/markdown";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ConfirmDialog, Modal } from "../components/dialog";
import { Notice } from "../components/notice";
import { Select } from "../components/select";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { actions, hint, panel } from "../styles";

export type AskingProps = {
  api: MeetingsApi;
  meeting: Meeting;
  /** read the meeting again (a question was asked, answered or deleted) */
  onChanged: () => Promise<void> | void;
  /** open a notebook (where it is shown in this app) */
  onOpenNotebook?: (id: string) => void;
};

const NEW = "__new__";

/** The meeting page's Ask: a question and its answer with the lines cited, the notebooks the meeting is
 * in, and Add to a notebook. */
export function Asking({ api, meeting, onChanged, onOpenNotebook }: AskingProps) {
  const [question, setQuestion] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<MeetingQuestion | null>(null);
  const fieldId = useId();

  const answering = meeting.questions.some((q) => q.status === "working");
  useEffect(() => {
    if (!answering) return;
    const t = setInterval(() => void onChanged(), 1500);
    return () => clearInterval(t);
  }, [answering, onChanged]);

  async function act(work: () => Promise<unknown>, fallback: string): Promise<boolean> {
    setProblem(null);
    setBusy(true);
    try {
      await work();
      await onChanged();
      return true;
    } catch (e) {
      setProblem(e instanceof Error ? e.message : fallback);
      return false;
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    void act(() => api.ask(meeting.id, q), "The question could not be asked.").then((ok) => {
      if (ok) setQuestion("");
    });
  }

  const inNone = meeting.notebooks.length === 0;
  return (
    <section className={cn(panel, "gap-4")} aria-label="Ask">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-ui-lg font-semibold">Ask</h2>
        <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
          <BookPlus /> Add to a notebook
        </Button>
      </div>
      <form className="grid gap-2" onSubmit={submit}>
        <label htmlFor={fieldId} className="sr-only">
          Your question about this meeting
        </label>
        <Textarea
          id={fieldId}
          rows={2}
          maxLength={4000}
          value={question}
          placeholder="What did they agree to do?"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className={cn(hint, "m-0")}>
            Answered by Notebooks from this meeting&rsquo;s transcript, with the lines it came from.
            {inNone
              ? " The first question adds the meeting to a new notebook named after it."
              : null}
          </p>
          <Button type="submit" disabled={busy || answering || !question.trim()}>
            {busy ? <Spinner /> : <MessageCircleQuestion />}
            Ask
          </Button>
        </div>
      </form>
      {problem ? (
        <Notice tone="error" title="That did not work" alert>
          {problem}
        </Notice>
      ) : null}

      {meeting.questions.length ? (
        <ul className="m-0 grid list-none gap-3 p-0">
          {[...meeting.questions].reverse().map((q) => (
            <li key={q.id} className="grid gap-2 rounded-lg border p-4" aria-label={q.question}>
              <div className="flex items-start justify-between gap-2">
                <p className="m-0 font-semibold">{q.question}</p>
                <span className={actions}>
                  {q.status === "working" ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void act(() => api.stopQuestion(q.id), "It could not stop.")}
                    >
                      <Square /> Stop
                    </Button>
                  ) : null}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDeleting(q)}
                    aria-label={`Delete the question: ${q.question}`}
                  >
                    <Trash2 />
                  </Button>
                </span>
              </div>
              {q.status === "working" ? (
                <p className={cn(hint, "m-0 flex items-center gap-2")} aria-live="polite">
                  <Spinner /> {q.stage || "Waiting"}
                </p>
              ) : q.status === "done" ? (
                <Answer q={q} onOpenNotebook={onOpenNotebook} />
              ) : (
                <p className="m-0 text-step--1 text-destructive">
                  {q.status === "cancelled" ? "Stopped." : q.error || "It could not be answered."}
                </p>
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {meeting.notebooks.length ? (
        <p className={cn(hint, "m-0")}>
          In {meeting.notebooks.length === 1 ? "the notebook" : "the notebooks"}{" "}
          {meeting.notebooks.map((n, i) => (
            <span key={n.notebook_id}>
              {i ? ", " : ""}
              {onOpenNotebook ? (
                <button
                  type="button"
                  className="text-primary underline"
                  onClick={() => onOpenNotebook(n.notebook_id)}
                >
                  {n.notebook_title}
                </button>
              ) : (
                <strong>{n.notebook_title}</strong>
              )}
            </span>
          ))}
          : ask across its other sources there.
        </p>
      ) : null}

      {adding ? (
        <NotebookDialog
          api={api}
          meeting={meeting}
          onCancel={() => setAdding(false)}
          onAdd={(to) => {
            setAdding(false);
            void act(() => api.addToNotebook(meeting.id, to), "It could not be added.");
          }}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title="Delete this question?"
          message="The question and its answer are deleted from this page. The notebook keeps the meeting."
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const q = deleting;
            setDeleting(null);
            void act(() => api.deleteQuestion(q.id), "It could not be deleted.");
          }}
        />
      ) : null}
    </section>
  );
}

function Answer({
  q,
  onOpenNotebook,
}: {
  q: MeetingQuestion;
  onOpenNotebook?: (id: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <div className="leading-relaxed">
        <Markdown text={q.reply} />
      </div>
      {q.citations.length ? (
        <ol className="m-0 grid list-none gap-1 p-0 text-step--1 text-muted-foreground">
          {q.citations.map((c, i) => (
            <li key={`${c.n ?? i}-${i}`} className="flex gap-2">
              <span className="font-semibold">[{c.n ?? i + 1}]</span>
              <span className="line-clamp-3">{c.text}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {onOpenNotebook && q.notebook_id ? (
        <span>
          <button
            type="button"
            className="text-step--1 text-primary underline"
            onClick={() => onOpenNotebook(q.notebook_id)}
          >
            Go on in the notebook
          </button>
        </span>
      ) : null}
    </div>
  );
}

function NotebookDialog({
  api,
  meeting,
  onAdd,
  onCancel,
}: {
  api: MeetingsApi;
  meeting: Meeting;
  onAdd: (to: { notebookId?: string; title?: string }) => void;
  onCancel: () => void;
}) {
  const [notebooks, setNotebooks] = useState<{ id: string; title: string }[] | null>(null);
  const [chosen, setChosen] = useState(NEW);
  const [title, setTitle] = useState(meeting.title);
  const [problem, setProblem] = useState<string | null>(null);
  const chooseId = useId();
  const nameId = useId();

  useEffect(() => {
    api.notebooks().then(setNotebooks, (e: unknown) => {
      setNotebooks([]);
      setProblem(e instanceof Error ? e.message : "The notebooks could not be read.");
    });
  }, [api]);

  const already = new Set(meeting.notebooks.map((n) => n.notebook_id));
  const options = [
    { value: NEW, label: "A new notebook" },
    ...(notebooks ?? []).map((n) => ({
      value: n.id,
      label: n.title,
      hint: already.has(n.id) ? "Added before: add the meeting as it is now" : undefined,
    })),
  ];
  function submit(e: FormEvent) {
    e.preventDefault();
    if (chosen === NEW) onAdd({ title: title.trim() || meeting.title });
    else onAdd({ notebookId: chosen });
  }
  return (
    <Modal label="Add to a notebook" onClose={onCancel}>
      <form className="grid gap-4" onSubmit={submit}>
        <h2 className="m-0 text-ui-lg font-semibold">Add to a notebook</h2>
        <p className={cn(hint, "m-0")}>
          The meeting&rsquo;s speakers, transcript and reports become a source of the notebook, to
          ask about with its other sources.
        </p>
        <label htmlFor={chooseId} className="grid gap-1.5 text-sm">
          <span className="text-muted-foreground">Notebook</span>
          <Select
            id={chooseId}
            value={chosen}
            onValueChange={setChosen}
            options={options}
            aria-label="Notebook"
            disabled={notebooks === null}
          />
        </label>
        {chosen === NEW ? (
          <label htmlFor={nameId} className="grid gap-1.5 text-sm">
            <span className="text-muted-foreground">Its name</span>
            <input
              id={nameId}
              value={title}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
              className="h-10 rounded-md border bg-transparent px-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </label>
        ) : null}
        {problem ? <p className="m-0 text-step--1 text-destructive">{problem}</p> : null}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={notebooks === null}>
            Add
          </Button>
        </div>
      </form>
    </Modal>
  );
}
