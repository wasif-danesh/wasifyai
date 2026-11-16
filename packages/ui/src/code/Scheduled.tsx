"use client";
// Scheduled (ADR-0105; mockups `scheduled`, `schedule-new`, `schedule-history`, `empty-scheduled`): work the
// agent does by itself at times the person sets. A run works on a copy of the project; what it changed
// waits until the person looks and applies it. Rules are plain (five kinds), never cron text. The screen
// says at the top that schedules run only while the app is open.
import type {
  CodeApi,
  CodeRule,
  CodeRunChanges,
  CodeSchedule,
  CodeScheduleRun,
  CodeScheduleTemplate,
  CodeWorkspace,
} from "@wasifyai/client";
import {
  ArrowLeft,
  CalendarClock,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleSlash,
  CircleX,
  Clock,
  Folder,
  Loader,
  type LucideIcon,
  Play,
  Plus,
  Square,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ConfirmDialog, Modal } from "../components/dialog";
import { EmptyState } from "../components/empty-state";
import { Input } from "../components/input";
import { Notice } from "../components/notice";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";

const say = (e: unknown, fallback: string) =>
  typeof e === "string" && e ? e : e instanceof Error && e.message ? e.message : fallback;

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SELECT =
  "h-9 rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** What happened at one due time, as a word with its tone. */
export function outcomeOf(run: CodeScheduleRun): { word: string; tone: string; icon: LucideIcon } {
  if (run.state === "waiting" || run.state === "running")
    return { word: "Running now", tone: "text-primary", icon: Loader };
  if (run.state === "missed") return { word: "Missed", tone: "text-muted-foreground", icon: Clock };
  if (run.state === "skipped")
    return { word: "Skipped: still running", tone: "text-muted-foreground", icon: CircleSlash };
  if (run.state === "failed")
    return { word: "Could not run", tone: "text-warn", icon: CircleAlert };
  if (run.note === "It was stopped.")
    return { word: "Stopped", tone: "text-muted-foreground", icon: Square };
  if (run.result === "passed") return { word: "Passed", tone: "text-ok", icon: CircleCheck };
  if (run.result === "failed")
    return { word: "Check failed", tone: "text-destructive", icon: CircleX };
  if (run.result === "could_not_check")
    return { word: "Could not check", tone: "text-warn", icon: CircleAlert };
  return { word: "Not checked", tone: "text-muted-foreground", icon: CircleDashed };
}

function Outcome({ run }: { run: CodeScheduleRun }) {
  const { word, tone, icon: Icon } = outcomeOf(run);
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-semibold", tone)}>
      <Icon aria-hidden="true" className="size-3.5" />
      {word}
    </span>
  );
}

const at = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

/** What a run left, in a few words. */
export function moreOf(run: CodeScheduleRun): string {
  const files = `${run.changed} file${run.changed === 1 ? "" : "s"} changed`;
  const parts: string[] = [];
  if (run.state === "done") {
    if (run.applied_at) parts.push(`${files}, applied by you`);
    else if (run.discarded_at && run.changed) parts.push(`${files}, let go`);
    else if (run.open && run.changed) parts.push(`${files}, waiting for you`);
    // a run its agent program stopped (a plan's limit, an ended sign-in) did not look at anything
    else if (!run.changed && !run.note?.startsWith("Stopped:"))
      parts.push("Nothing needed changing");
  }
  if (run.note) parts.push(run.note === "run now" ? "Started with Run now" : run.note);
  if (run.stands_for > 1) parts.push(`stands for ${run.stands_for} missed times`);
  return parts.join(". ");
}

function Switch({
  on,
  label,
  onChange,
}: {
  on: boolean;
  label: string;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={cn(
        "relative h-6 w-10 shrink-0 rounded-full border outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
        on ? "border-primary bg-primary" : "bg-muted",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "absolute top-0.5 size-4.5 rounded-full bg-background shadow transition-[inset-inline-start]",
          on ? "start-[1.125rem]" : "start-0.5",
        )}
      />
    </button>
  );
}

/** "Open Wasify AI when I log in, and keep it in the menu bar": the desktop shell's switch. */
export type StayOpen = {
  get: () => Promise<{ supported: boolean; on: boolean }>;
  set: (on: boolean) => Promise<{ supported: boolean; on: boolean }>;
};

function Awake({ stayOpen }: { stayOpen?: StayOpen }) {
  const [stays, setStays] = useState<{ supported: boolean; on: boolean } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let gone = false;
    stayOpen
      ?.get()
      .then((now) => {
        if (!gone) setStays(now);
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [stayOpen]);
  return (
    <Notice
      tone="info"
      title="Schedules run only while Wasify AI is open and this computer is awake"
    >
      A time that passes while the app is closed or the computer sleeps is written down as missed. A
      schedule can ask to run once when the app is back.
      {stayOpen && stays?.supported ? (
        <span className="mt-2 flex items-start gap-2.5">
          <Switch
            on={stays.on}
            label="Open Wasify AI when I log in, and keep it in the menu bar"
            onChange={(on) => {
              setProblem(null);
              stayOpen
                .set(on)
                .then(setStays)
                .catch((e) => setProblem(say(e, "That could not be changed.")));
            }}
          />
          <span>
            Open Wasify AI when I log in, and keep it in the menu bar
            <br />
            <span className="text-xs">
              {stays.on
                ? "On: closing the window leaves Wasify AI open. Quit it from its item in the menu bar."
                : "Off: closing the window quits Wasify AI, and its schedules wait."}
            </span>
            {problem ? (
              <span role="alert" className="block text-xs text-destructive">
                {problem}
              </span>
            ) : null}
          </span>
        </span>
      ) : null}
    </Notice>
  );
}

type View =
  | { at: "list" }
  | { at: "new" }
  | { at: "one"; id: string }
  | { at: "change"; schedule: CodeSchedule };

export function Scheduled({
  api,
  stayOpen,
  onOpenProjects,
  onOpenSession,
}: {
  api: CodeApi;
  /** The desktop shell's switch for staying open; none: the switch is not shown. */
  stayOpen?: StayOpen;
  /** Where a project is opened (Code, Projects). */
  onOpenProjects: () => void;
  /** Open a run's session, to read what the agent did. */
  onOpenSession: (sessionId: string) => void;
}) {
  const [view, setView] = useState<View>({ at: "list" });
  const [items, setItems] = useState<CodeSchedule[] | null>(null);
  const [zone, setZone] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const read = useCallback(async () => {
    try {
      const found = await api.schedules();
      setItems(found.items);
      setZone(found.time_zone);
      setProblem(null);
    } catch (e) {
      setProblem(say(e, "The schedules could not be read."));
    }
  }, [api]);
  useEffect(() => {
    void read();
  }, [read]);
  // while a run is going the list is read again, so its end is shown without a reload
  const running = (items ?? []).some((s) => s.running);
  useEffect(() => {
    if (!running || view.at !== "list") return;
    const timer = setInterval(() => void read(), 2000);
    return () => clearInterval(timer);
  }, [running, view.at, read]);

  const act = async (work: () => Promise<unknown>, fallback: string) => {
    try {
      await work();
      await read();
    } catch (e) {
      setProblem(say(e, fallback));
    }
  };

  if (view.at === "new" || view.at === "change") {
    const back: View = view.at === "change" ? { at: "one", id: view.schedule.id } : { at: "list" };
    return (
      <Form
        api={api}
        zone={zone}
        editing={view.at === "change" ? view.schedule : undefined}
        onOpenProjects={onOpenProjects}
        onClose={() => setView(back)}
        onSaved={() => {
          setView(back);
          void read();
        }}
      />
    );
  }
  if (view.at === "one")
    return (
      <One
        api={api}
        id={view.id}
        onBack={() => {
          setView({ at: "list" });
          void read();
        }}
        onOpenSession={onOpenSession}
        onChange={(schedule) => setView({ at: "change", schedule })}
      />
    );

  return (
    <div className="mx-auto grid w-[min(100%-2rem,56rem)] gap-5 pt-8 pb-16">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid gap-1.5">
          <h1 className="m-0 text-2xl font-semibold">Scheduled</h1>
          <p className="m-0 max-w-[60ch] text-muted-foreground">
            Work the agent does by itself at times you set. It works on a copy of the project, and
            you look at the result before anything is applied.
          </p>
        </div>
        {items?.length ? (
          <Button onClick={() => setView({ at: "new" })}>
            <Plus /> New schedule
          </Button>
        ) : null}
      </div>
      <Awake stayOpen={stayOpen} />
      {problem ? (
        <Notice tone="error" title="That did not work">
          {problem}
        </Notice>
      ) : null}
      {items === null ? (
        problem ? null : (
          <div className="grid place-items-center py-10">
            <Spinner />
          </div>
        )
      ) : items.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title="No schedules yet"
          text="A schedule asks the agent to do something by itself: every night, on chosen weekdays, or once. It works on a copy of the project, and you look at the result before anything is applied."
          action={
            <Button onClick={() => setView({ at: "new" })}>
              <Plus /> New schedule
            </Button>
          }
        />
      ) : (
        <ul className="m-0 grid list-none gap-2 p-0">
          {items.map((s) => (
            <li
              key={s.id}
              className="flex flex-wrap items-start gap-3 rounded-lg border bg-surface px-3.5 py-3"
            >
              <div className="grid min-w-0 flex-1 gap-1">
                <h2
                  className={cn(
                    "m-0 truncate text-sm font-semibold",
                    s.enabled ? "" : "text-muted-foreground",
                  )}
                >
                  {s.title}
                </h2>
                <p className="m-0 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <Folder aria-hidden="true" className="size-3.5" />
                    {s.project || "The project is gone"}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <CalendarClock aria-hidden="true" className="size-3.5" />
                    {s.rule_words}, {s.time_zone}
                  </span>
                </p>
                <p className="m-0 text-xs text-muted-foreground">
                  {s.enabled && s.next_due ? (
                    <>
                      <strong className="font-semibold text-foreground">
                        Next: {at(s.next_due)}
                      </strong>
                      , if the app is open and the computer is awake
                    </>
                  ) : s.enabled ? (
                    "It has no further time."
                  ) : (
                    "Off. It will not run."
                  )}
                </p>
                <p className="m-0 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                  {s.last ? (
                    <>
                      <Outcome run={s.last} />
                      <span>
                        {at(s.last.due_at)}
                        {moreOf(s.last) ? ` · ${moreOf(s.last)}` : ""}
                      </span>
                    </>
                  ) : (
                    "Has not run yet"
                  )}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Switch
                  on={s.enabled}
                  label={`${s.title}: ${s.enabled ? "on" : "off"}`}
                  onChange={(on) =>
                    void act(
                      () => api.changeSchedule(s.id, { enabled: on }),
                      "That could not be changed.",
                    )
                  }
                />
                {s.running && s.last ? (
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label={`Stop the run of ${s.title}`}
                    onClick={() => {
                      const run = s.last;
                      if (run) void act(() => api.stopRun(run.id), "It could not be stopped.");
                    }}
                  >
                    <Square /> Stop
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label={`Run ${s.title} now`}
                    onClick={() =>
                      void act(() => api.runSchedule(s.id), "It could not be started.")
                    }
                  >
                    <Play /> Run now
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`History of ${s.title}`}
                  onClick={() => setView({ at: "one", id: s.id })}
                >
                  History
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---- making one ---------------------------------------------------------------------------------

type Kind = CodeRule["kind"];
const KINDS: [Kind, string, string][] = [
  ["daily", "Every day", "At the same time each day."],
  ["weekdays", "On chosen weekdays", "The days you pick, at one time."],
  ["monthly", "Every month", "On one day of the month, at one time."],
  ["every", "Every so many minutes or hours", "Counted from when the schedule is saved."],
  ["once", "Once", "On one day, at one time."],
];

type Draft = {
  kind: Kind;
  time: string;
  days: number[];
  day: number;
  n: number;
  unit: "minutes" | "hours";
  date: string;
};

const draftOf = (rule?: CodeRule): Draft => {
  const d: Draft = {
    kind: "daily",
    time: "09:00",
    days: [0, 1, 2, 3, 4],
    day: 1,
    n: 2,
    unit: "hours",
    date: new Date(Date.now() + 86_400_000).toISOString().slice(0, 10),
  };
  if (!rule) return d;
  d.kind = rule.kind;
  if ("time" in rule) d.time = rule.time;
  if (rule.kind === "weekdays") d.days = rule.days;
  if (rule.kind === "monthly") d.day = rule.day;
  if (rule.kind === "once") d.date = rule.date;
  if (rule.kind === "every") {
    d.unit = rule.hours ? "hours" : "minutes";
    d.n = rule.hours ?? rule.minutes ?? 30;
  }
  return d;
};

/** The rule a person set in the form. */
export function ruleOf(d: Draft): CodeRule {
  if (d.kind === "daily") return { kind: "daily", time: d.time };
  if (d.kind === "weekdays")
    return { kind: "weekdays", days: [...d.days].sort((a, b) => a - b), time: d.time };
  if (d.kind === "monthly") return { kind: "monthly", day: d.day, time: d.time };
  if (d.kind === "once") return { kind: "once", date: d.date, time: d.time };
  return d.unit === "hours" ? { kind: "every", hours: d.n } : { kind: "every", minutes: d.n };
}

function Form({
  api,
  zone,
  editing,
  onOpenProjects,
  onClose,
  onSaved,
}: {
  api: CodeApi;
  zone: string;
  /** a schedule that is being changed; none: a new one */
  editing?: CodeSchedule;
  onOpenProjects: () => void;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [projects, setProjects] = useState<CodeWorkspace[] | null>(null);
  const [templates, setTemplates] = useState<CodeScheduleTemplate[]>([]);
  const [project, setProject] = useState(editing?.workspace_id ?? "");
  const [title, setTitle] = useState(editing?.title ?? "");
  const [request, setRequest] = useState(editing?.request ?? "");
  const [draft, setDraft] = useState<Draft>(() => draftOf(editing?.rule));
  const [missed, setMissed] = useState(editing?.run_when_missed ?? true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const ids = { project: useId(), request: useId(), time: useId(), n: useId(), date: useId() };
  const set = (more: Partial<Draft>) => setDraft((d) => ({ ...d, ...more }));

  useEffect(() => {
    let gone = false;
    Promise.all([api.workspaces(), api.scheduleTemplates()])
      .then(([found, short]) => {
        if (gone) return;
        setProjects(found);
        setProject((p) => p || found[0]?.id || "");
        setTemplates(short);
      })
      .catch((e) => {
        if (!gone) setProblem(say(e, "The projects could not be read."));
      });
    return () => {
      gone = true;
    };
  }, [api]);

  const save = async () => {
    setBusy(true);
    try {
      const what = { request, rule: ruleOf(draft), title, run_when_missed: missed };
      if (editing) await api.changeSchedule(editing.id, what);
      else await api.addSchedule({ workspace_id: project, ...what });
      onSaved();
    } catch (e) {
      setProblem(say(e, "The schedule could not be saved."));
      setBusy(false);
    }
  };
  const timeBox = (
    <span className="inline-flex items-center gap-2 text-sm">
      <label htmlFor={ids.time} className="text-muted-foreground">
        At
      </label>
      <Input
        id={ids.time}
        type="time"
        value={draft.time}
        onChange={(e) => set({ time: e.target.value })}
        className="w-28"
      />
    </span>
  );

  return (
    <div className="mx-auto grid w-[min(100%-2rem,42rem)] gap-5 pt-8 pb-16">
      <div className="grid justify-items-start gap-1">
        <Button variant="link" size="sm" onClick={onClose} className="px-0">
          <ArrowLeft /> Scheduled
        </Button>
        <h1 className="m-0 text-2xl font-semibold">
          {editing ? "Change the schedule" : "New schedule"}
        </h1>
      </div>
      {projects !== null && projects.length === 0 ? (
        <Notice
          tone="info"
          title="Open a project first"
          actions={
            <Button size="sm" variant="outline" onClick={onOpenProjects}>
              Open Projects
            </Button>
          }
        >
          A schedule runs in a project. Open its folder in Code, Projects, then come back.
        </Notice>
      ) : null}
      <div className="grid gap-5 rounded-lg border bg-surface p-4">
        <div className="grid gap-1.5">
          <label htmlFor={ids.project} className="text-sm font-semibold">
            Project
          </label>
          <select
            id={ids.project}
            value={project}
            disabled={Boolean(editing)}
            onChange={(e) => setProject(e.target.value)}
            className={SELECT}
          >
            {(projects ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-1.5">
          <label htmlFor={ids.request} className="text-sm font-semibold">
            What should be done
          </label>
          <Textarea
            id={ids.request}
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            placeholder="Say it as you would in the chat."
            className="min-h-24"
          />
          {templates.length ? (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-muted-foreground">Or start from a template:</span>
              {templates.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  title={t.description}
                  onClick={() => {
                    setRequest(t.request);
                    setTitle(t.title);
                    setDraft(draftOf(t.rule));
                  }}
                  className="rounded-full border px-2.5 py-1 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t.title}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <fieldset className="m-0 grid gap-2 border-0 p-0">
          <legend className="mb-1.5 p-0 text-sm font-semibold">When</legend>
          {KINDS.map(([kind, label, about]) => (
            <div key={kind} className="grid gap-2 rounded-md border px-3 py-2">
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="when"
                  className="mt-1"
                  checked={draft.kind === kind}
                  onChange={() => set({ kind })}
                />
                <span>
                  <span className="font-semibold">{label}</span>
                  <br />
                  <span className="text-xs text-muted-foreground">{about}</span>
                </span>
              </label>
              {draft.kind !== kind ? null : kind === "weekdays" ? (
                <div className="grid gap-2 ps-6">
                  <fieldset className="m-0 flex flex-wrap gap-1 border-0 p-0" aria-label="Weekdays">
                    {DAYS.map((d, i) => (
                      <button
                        key={d}
                        type="button"
                        aria-pressed={draft.days.includes(i)}
                        onClick={() =>
                          set({
                            days: draft.days.includes(i)
                              ? draft.days.filter((x) => x !== i)
                              : [...draft.days, i],
                          })
                        }
                        className="rounded-full border px-2.5 py-1 text-xs outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring aria-pressed:bg-accent aria-pressed:font-semibold"
                      >
                        {d}
                      </button>
                    ))}
                  </fieldset>
                  {timeBox}
                </div>
              ) : kind === "monthly" ? (
                <div className="grid gap-1 ps-6">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <label htmlFor={ids.n} className="text-muted-foreground">
                      On day
                    </label>
                    <Input
                      id={ids.n}
                      type="number"
                      min={1}
                      max={31}
                      value={draft.day}
                      onChange={(e) => set({ day: Number(e.target.value) || 1 })}
                      className="w-20"
                    />
                    {timeBox}
                  </div>
                  <p className="m-0 text-xs text-muted-foreground">
                    In a month without that day it runs on the month’s last day.
                  </p>
                </div>
              ) : kind === "every" ? (
                <div className="grid gap-1 ps-6">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <label htmlFor={ids.n} className="text-muted-foreground">
                      Every
                    </label>
                    <Input
                      id={ids.n}
                      type="number"
                      min={draft.unit === "minutes" ? 5 : 1}
                      value={draft.n}
                      onChange={(e) => set({ n: Number(e.target.value) || 1 })}
                      className="w-20"
                    />
                    <select
                      aria-label="Minutes or hours"
                      value={draft.unit}
                      onChange={(e) => set({ unit: e.target.value as Draft["unit"] })}
                      className={SELECT}
                    >
                      <option value="minutes">minutes</option>
                      <option value="hours">hours</option>
                    </select>
                  </div>
                  <p className="m-0 text-xs text-muted-foreground">Five minutes at the least.</p>
                </div>
              ) : kind === "once" ? (
                <div className="flex flex-wrap items-center gap-2 ps-6 text-sm">
                  <label htmlFor={ids.date} className="text-muted-foreground">
                    On
                  </label>
                  <Input
                    id={ids.date}
                    type="date"
                    value={draft.date}
                    onChange={(e) => set({ date: e.target.value })}
                    className="w-40"
                  />
                  {timeBox}
                </div>
              ) : (
                <div className="ps-6">{timeBox}</div>
              )}
            </div>
          ))}
          <p className="m-0 text-xs text-muted-foreground">
            Times are clock times in {zone || "this computer’s time zone"}, also when the clocks
            change.
          </p>
        </fieldset>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={missed}
            onChange={(e) => setMissed(e.target.checked)}
          />
          <span>
            <span className="font-semibold">Run when missed</span>
            <br />
            <span className="text-muted-foreground">
              If the app was closed or the computer asleep at the time, run once when it is back, as
              long as less than a day has passed. Otherwise the time is written down as missed.
            </span>
          </span>
        </label>
        <details className="text-sm">
          <summary className="cursor-pointer font-semibold">How a scheduled run works</summary>
          <ul className="mt-2 mb-0 grid gap-1 ps-5 text-muted-foreground">
            <li>
              It works on a copy of the project. Your files change only when you look at the result
              and apply it.
            </li>
            <li>
              Nobody is there to answer, so anything that would ask you is refused and written down.
            </li>
            <li>
              It ends with the same check as a chat: passed, failed, not checked or could not check.
            </li>
            <li>
              One run at a time: if the last run is still going when the next time comes, that time
              is skipped.
            </li>
          </ul>
        </details>
        {problem ? (
          <p role="alert" className="m-0 text-sm text-destructive">
            {problem}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => void save()}
            disabled={
              busy ||
              !project ||
              !request.trim() ||
              (draft.kind === "weekdays" && !draft.days.length)
            }
          >
            {busy ? <Spinner className="size-3.5" /> : null} Save the schedule
          </Button>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---- one schedule: its history, and a run's changes ---------------------------------------------

function One({
  api,
  id,
  onBack,
  onOpenSession,
  onChange,
}: {
  api: CodeApi;
  id: string;
  onBack: () => void;
  onChange: (schedule: CodeSchedule) => void;
  onOpenSession: (sessionId: string) => void;
}) {
  const [found, setFound] = useState<CodeSchedule | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [said, setSaid] = useState<string | null>(null);
  const [looking, setLooking] = useState<CodeRunChanges | null>(null);
  const [removing, setRemoving] = useState(false);

  const read = useCallback(async () => {
    try {
      setFound(await api.schedule(id));
    } catch (e) {
      setProblem(say(e, "The schedule could not be read."));
    }
  }, [api, id]);
  useEffect(() => {
    void read();
  }, [read]);
  useEffect(() => {
    if (!found?.running) return;
    const timer = setInterval(() => void read(), 2000);
    return () => clearInterval(timer);
  }, [found?.running, read]);

  const act = async (work: () => Promise<unknown>, fallback: string) => {
    try {
      setProblem(null);
      await work();
      await read();
    } catch (e) {
      setProblem(say(e, fallback));
    }
  };
  const runs = found?.runs ?? [];
  const waiting = runs.find((r) => r.state === "done" && r.open);
  const apply = (run: CodeScheduleRun) =>
    act(async () => {
      const done = await api.applyRun(run.id);
      setLooking(null);
      const n = done.applied.length;
      setSaid(
        `${n} file${n === 1 ? " was" : "s were"} written into the project.${
          done.left.length
            ? ` Left as you have ${done.left.length === 1 ? "it" : "them"}, because you changed ${
                done.left.length === 1 ? "it" : "them"
              } meanwhile: ${done.left.join(", ")}.`
            : ""
        }`,
      );
    }, "The changes could not be applied.");
  const letGo = (run: CodeScheduleRun) =>
    act(async () => {
      await api.discardRun(run.id);
      setLooking(null);
      setSaid("The run’s changes were let go. Your project is as it was.");
    }, "That did not work.");

  return (
    <div className="mx-auto grid w-[min(100%-2rem,56rem)] gap-5 pt-8 pb-16">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid justify-items-start gap-1">
          <Button variant="link" size="sm" onClick={onBack} className="px-0">
            <ArrowLeft /> Scheduled
          </Button>
          <h1 className="m-0 text-2xl font-semibold">{found?.title ?? "A schedule"}</h1>
          {found ? (
            <>
              <p className="m-0 text-sm text-muted-foreground">
                {found.project} · {found.rule_words}, {found.time_zone} · Run when missed:{" "}
                {found.run_when_missed ? "on" : "off"}
              </p>
              <p className="m-0 text-sm text-muted-foreground">
                {found.enabled && found.next_due ? (
                  <>
                    <strong className="font-semibold text-foreground">
                      Next: {at(found.next_due)}
                    </strong>
                    , if the app is open and the computer is awake
                  </>
                ) : found.enabled ? (
                  "It has no further time."
                ) : (
                  "Off. It will not run."
                )}
              </p>
            </>
          ) : null}
        </div>
        {found ? (
          <div className="flex flex-wrap items-center gap-2">
            <Switch
              on={found.enabled}
              label={`${found.title}: ${found.enabled ? "on" : "off"}`}
              onChange={(on) =>
                void act(
                  () => api.changeSchedule(id, { enabled: on }),
                  "That could not be changed.",
                )
              }
            />
            <Button
              size="sm"
              disabled={found.running}
              onClick={() => void act(() => api.runSchedule(id), "It could not be started.")}
            >
              <Play /> Run now
            </Button>
            <Button size="sm" variant="outline" onClick={() => onChange(found)}>
              Change
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setRemoving(true)}>
              <Trash2 /> Delete
            </Button>
          </div>
        ) : null}
      </div>
      {problem ? (
        <Notice tone="error" title="That did not work">
          {problem}
        </Notice>
      ) : null}
      {said ? (
        <Notice tone="ok" title="Done">
          {said}
        </Notice>
      ) : null}
      {found ? (
        <details className="rounded-lg border bg-surface px-3.5 py-2.5 text-sm">
          <summary className="cursor-pointer font-semibold">What it asks the agent</summary>
          <p className="mt-2 mb-0 whitespace-pre-wrap text-muted-foreground">{found.request}</p>
        </details>
      ) : null}
      {waiting ? (
        <Notice
          tone={waiting.changed ? "ok" : "info"}
          title={
            waiting.changed
              ? `The run of ${at(waiting.due_at)} changed ${waiting.changed} file${
                  waiting.changed === 1 ? "" : "s"
                }, in its copy`
              : `The run of ${at(waiting.due_at)} changed nothing`
          }
          actions={
            <>
              {waiting.changed ? (
                <Button
                  size="sm"
                  onClick={() =>
                    void act(
                      async () => setLooking(await api.runChanges(waiting.id)),
                      "The changes could not be read.",
                    )
                  }
                >
                  Look at the changes
                </Button>
              ) : null}
              {waiting.session_id ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => waiting.session_id && onOpenSession(waiting.session_id)}
                >
                  Read what the agent did
                </Button>
              ) : null}
              <Button size="sm" variant="ghost" onClick={() => void letGo(waiting)}>
                Let it go
              </Button>
            </>
          }
        >
          Your project has not been touched.{" "}
          {waiting.changed ? "Look at the changes, then apply them or let them go." : ""}
          {waiting.note && waiting.note !== "run now" ? ` ${waiting.note}` : ""}
        </Notice>
      ) : null}
      {found === null ? (
        problem ? null : (
          <div className="grid place-items-center py-10">
            <Spinner />
          </div>
        )
      ) : runs.length === 0 ? (
        <EmptyState
          icon={Clock}
          size="sm"
          title="It has not run yet"
          text="Every time it comes due is written down here, with what happened."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-surface">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-start text-xs text-muted-foreground">
                <th className="px-3 py-2 text-start font-semibold">It was due</th>
                <th className="px-3 py-2 text-start font-semibold">What happened</th>
                <th className="px-3 py-2 text-start font-semibold">More</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-t align-top">
                  <td className="px-3 py-2 whitespace-nowrap">{at(r.due_at)}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <Outcome run={r} />
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {moreOf(r)}
                    {r.state === "running" ? (
                      <Button
                        size="sm"
                        variant="outline"
                        className="ms-2"
                        onClick={() =>
                          void act(() => api.stopRun(r.id), "It could not be stopped.")
                        }
                      >
                        <Square /> Stop
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {looking && waiting ? (
        <Modal label="What the run changed" onClose={() => setLooking(null)} wide>
          <p className="m-0 text-sm text-muted-foreground">
            These files are changed in the run’s copy of {looking.project}. Applying writes them
            into the project. A file you changed meanwhile is left as you have it.
          </p>
          <ul className="m-0 grid max-h-80 list-none gap-1 overflow-auto p-0 text-sm">
            {looking.files.map((f) => (
              <li
                key={f.path}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-1.5"
              >
                <code className="min-w-0 truncate text-xs">{f.path}</code>
                <span className="text-xs text-muted-foreground">
                  {f.what}
                  {f.conflict ? (
                    <strong className="ms-2 font-semibold text-warn">
                      you changed it meanwhile: it will be left
                    </strong>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => void letGo(waiting)}>
              Let it go
            </Button>
            <Button variant="outline" onClick={() => setLooking(null)}>
              Not now
            </Button>
            <Button
              onClick={() => void apply(waiting)}
              disabled={looking.files.every((f) => f.conflict)}
            >
              Apply to the project
            </Button>
          </div>
        </Modal>
      ) : null}
      {removing && found ? (
        <ConfirmDialog
          title={`Delete “${found.title}”?`}
          message="The schedule, its history and the copies of its runs are removed. Your project is not touched."
          confirmLabel="Delete"
          destructive
          onConfirm={() => {
            setRemoving(false);
            api
              .removeSchedule(id)
              .then(onBack)
              .catch((e) => setProblem(say(e, "It could not be deleted.")));
          }}
          onCancel={() => setRemoving(false)}
        />
      ) : null}
    </div>
  );
}
