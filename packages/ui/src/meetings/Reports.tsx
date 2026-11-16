// Reports of a meeting (ADR-0108 decision 15, stage MT4): a summary, minutes, action items and the
// rest, written from a template by the person's chosen chat model; and templates of their own.
import type { Meeting, MeetingReport, MeetingsApi, ReportTemplate } from "@wasifyai/client";
import { Copy, Download, FilePlus2, PenLine, Square, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useId, useState } from "react";
import { Markdown } from "../chat/markdown";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ConfirmDialog, Modal } from "../components/dialog";
import { Notice } from "../components/notice";
import { Bar } from "../components/progress-bar";
import { Select } from "../components/select";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";
import { fileNameFor, savedText, useSaveCopy } from "../save";
import { actions, hint, panel } from "../styles";

export type ReportsProps = {
  api: MeetingsApi;
  meeting: Meeting;
  /** read the meeting again (a report was started, finished or deleted) */
  onChanged: () => Promise<void> | void;
};

/** The meeting page's Reports: choose a template and Write; each report as it is written, then its
 * text with Copy, Save and Delete. */
export function Reports({ api, meeting, onChanged }: ReportsProps) {
  const [templates, setTemplates] = useState<ReportTemplate[] | null>(null);
  const [chosen, setChosen] = useState("summary");
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [making, setMaking] = useState(false);
  const [deleting, setDeleting] = useState<MeetingReport | null>(null);
  const [dropping, setDropping] = useState<ReportTemplate | null>(null);
  const [busy, setBusy] = useState(false);
  const saveCopy = useSaveCopy();
  const fieldId = useId();

  useEffect(() => {
    api.templates().then(setTemplates, () => setTemplates([]));
  }, [api]);

  const writing = meeting.reports.some((r) => r.status === "working");
  useEffect(() => {
    if (!writing) return;
    const t = setInterval(() => void onChanged(), 1500);
    return () => clearInterval(t);
  }, [writing, onChanged]);

  async function act(work: () => Promise<unknown>, fallback: string) {
    setProblem(null);
    setNote(null);
    setBusy(true);
    try {
      await work();
      await onChanged();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  const own = templates?.find((t) => t.id === chosen && t.own) ?? null;
  const options = (templates ?? []).map((t) => ({
    value: t.id,
    label: t.title,
    hint: t.own ? "Your own" : undefined,
  }));

  return (
    <section className={cn(panel, "gap-4")} aria-label="Reports">
      <h2 className="text-ui-lg font-semibold">Reports</h2>
      <div className="flex flex-wrap items-end gap-2.5">
        <label htmlFor={fieldId} className="grid min-w-56 flex-1 gap-1.5 text-sm sm:max-w-xs">
          <span className="text-muted-foreground">Report</span>
          <Select
            id={fieldId}
            value={templates ? chosen : undefined}
            onValueChange={setChosen}
            options={options}
            aria-label="Report"
            disabled={!templates}
          />
        </label>
        <Button
          onClick={() => void act(() => api.writeReport(meeting.id, chosen), "It could not start.")}
          disabled={busy || writing || !templates}
        >
          {busy ? <Spinner /> : <PenLine />}
          Write
        </Button>
        <Button variant="outline" onClick={() => setMaking(true)}>
          <FilePlus2 /> New template
        </Button>
        {own ? (
          <Button variant="ghost" onClick={() => setDropping(own)}>
            <Trash2 /> Delete template
          </Button>
        ) : null}
      </div>
      <p className={cn(hint, "m-0")}>
        Written by your chat model from the transcript, using only what was said, in the language of
        the meeting. Name the speakers first, so the report uses their names.
      </p>
      {note ? <p className={hint}>{note}</p> : null}
      {problem ? (
        <Notice tone="error" title="That did not work" alert>
          {problem}
        </Notice>
      ) : null}

      {meeting.reports.length ? (
        <ul className="m-0 grid list-none gap-3 p-0">
          {[...meeting.reports].reverse().map((r) => (
            <li key={r.id} className="grid gap-2 rounded-lg border p-4" aria-label={r.title}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="m-0 font-semibold">{r.title}</h3>
                <span className={actions}>
                  {r.status === "done" ? (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          void navigator.clipboard
                            ?.writeText(r.text)
                            .then(() => setNote("Copied."))
                            .catch(() => setProblem("It could not be copied."))
                        }
                      >
                        <Copy /> Copy
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          void act(async () => {
                            const out = await saveCopy({
                              name: fileNameFor(`${meeting.title} ${r.title}`, "md", "report"),
                              blob: () => api.exportReport(r.id),
                            });
                            if (out) setNote(savedText(out));
                          }, "It could not be saved.")
                        }
                      >
                        <Download /> Save
                      </Button>
                    </>
                  ) : null}
                  {r.status === "working" ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void act(() => api.stopReport(r.id), "It could not stop.")}
                    >
                      <Square /> Stop
                    </Button>
                  ) : null}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDeleting(r)}
                    aria-label={`Delete ${r.title}`}
                  >
                    <Trash2 />
                  </Button>
                </span>
              </div>
              {r.status === "working" ? (
                <div className="grid gap-1.5" aria-live="polite">
                  <span className={hint}>{r.stage || "Waiting"}</span>
                  <Bar value={r.progress} />
                </div>
              ) : r.status === "done" ? (
                <div className="leading-relaxed">
                  <Markdown text={r.text} />
                </div>
              ) : (
                <p className="m-0 text-step--1 text-destructive">
                  {r.status === "cancelled" ? "Stopped." : r.error || "It could not be written."}
                </p>
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {making ? (
        <TemplateDialog
          onCancel={() => setMaking(false)}
          onSave={(title, instructions) => {
            setMaking(false);
            void act(async () => {
              const t = await api.addTemplate(title, instructions);
              setTemplates((all) => [...(all ?? []), t]);
              setChosen(t.id);
            }, "The template could not be kept.");
          }}
        />
      ) : null}
      {deleting ? (
        <ConfirmDialog
          title={`Delete the ${deleting.title.toLowerCase()}?`}
          message="This report is deleted; the meeting stays. This cannot be undone."
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const r = deleting;
            setDeleting(null);
            void act(() => api.deleteReport(r.id), "It could not be deleted.");
          }}
        />
      ) : null}
      {dropping ? (
        <ConfirmDialog
          title={`Delete the template "${dropping.title}"?`}
          message="Reports already written with it stay."
          onCancel={() => setDropping(null)}
          onConfirm={() => {
            const t = dropping;
            setDropping(null);
            void act(async () => {
              await api.deleteTemplate(t.id);
              setTemplates((all) => (all ?? []).filter((x) => x.id !== t.id));
              setChosen("summary");
            }, "It could not be deleted.");
          }}
        />
      ) : null}
    </section>
  );
}

function TemplateDialog({
  onSave,
  onCancel,
}: {
  onSave: (title: string, instructions: string) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const titleId = useId();
  const textId = useId();
  const ok = title.trim() && instructions.trim();
  function submit(e: FormEvent) {
    e.preventDefault();
    if (ok) onSave(title.trim(), instructions.trim());
  }
  return (
    <Modal label="New report template" onClose={onCancel}>
      <form className="grid gap-4" onSubmit={submit}>
        <label htmlFor={titleId} className="grid gap-1.5 text-sm">
          <span className="text-muted-foreground">Name</span>
          <input
            id={titleId}
            // biome-ignore lint/a11y/noAutofocus: the dialog exists to write a template
            autoFocus
            value={title}
            maxLength={80}
            onChange={(e) => setTitle(e.target.value)}
            className="h-10 rounded-md border bg-transparent px-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </label>
        <label htmlFor={textId} className="grid gap-1.5 text-sm">
          <span className="text-muted-foreground">What the report says</span>
          <Textarea
            id={textId}
            rows={5}
            maxLength={4000}
            value={instructions}
            placeholder="What the client asked for, what we promised, and by when."
            onChange={(e) => setInstructions(e.target.value)}
          />
        </label>
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={!ok}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}
