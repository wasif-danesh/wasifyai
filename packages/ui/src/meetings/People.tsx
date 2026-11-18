"use client";

// People (ADR-0108 decisions 11 and 12, stage MT3): everyone named in a meeting, with how many
// meetings and voiceprints of them are kept; rename them, or forget them with every voiceprint.
import type { MeetingPerson, MeetingsApi } from "@wasifyai/client";
import { Pencil, Trash2, UserRound, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { ConfirmDialog, NameDialog } from "../components/dialog";
import { EmptyState } from "../components/empty-state";
import { Notice } from "../components/notice";
import { PageHero } from "../components/page-hero";
import { Spinner } from "../components/spinner";
import { actions, hint, page, panel } from "../styles";

export type PeopleProps = {
  api: MeetingsApi;
  /** open the list of meetings */
  onOpenMeetings?: () => void;
  /** on the web: no voiceprints are kept, so no one is suggested by voice */
  hosted?: boolean;
};

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The people the meetings know: named by the person, suggested by voice in later meetings. */
export function People({ api, onOpenMeetings, hosted }: PeopleProps) {
  const [people, setPeople] = useState<MeetingPerson[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<MeetingPerson | null>(null);
  const [forgetting, setForgetting] = useState<MeetingPerson | null>(null);

  const load = useCallback(async () => {
    try {
      setPeople(await api.people());
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "People could not be read.");
      setPeople([]);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(work: () => Promise<unknown>, fallback: string) {
    setProblem(null);
    try {
      await work();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : fallback);
    }
    await load();
  }

  return (
    <div className={page}>
      <PageHero eyebrow="Meetings" title="People">
        {hosted
          ? "Everyone you have named in a meeting."
          : "Everyone you have named in a meeting. Their voices are kept on this computer, so later meetings can suggest who is speaking; a name is only given when you say Yes."}
      </PageHero>
      {problem ? (
        <Notice tone="error" title="That did not work" alert>
          {problem}
        </Notice>
      ) : null}
      <section className={cn(panel, "gap-3")} aria-label="People">
        {people === null ? (
          <Spinner />
        ) : people.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No one yet"
            text="Open a meeting and choose a speaker to give them a name."
            action={
              onOpenMeetings ? (
                <Button variant="outline" onClick={onOpenMeetings}>
                  View meetings
                </Button>
              ) : undefined
            }
          />
        ) : (
          <ul className="m-0 grid list-none gap-2 p-0">
            {people.map((p) => (
              <li
                key={p.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
                aria-label={p.name}
              >
                <span className="flex items-center gap-3">
                  <span className="grid size-9 place-items-center rounded-full bg-muted">
                    <UserRound className="size-4" aria-hidden />
                  </span>
                  <span className="grid">
                    <strong>{p.name}</strong>
                    <span className={cn(hint, "m-0")}>
                      {count(p.meetings, "meeting", "meetings")},{" "}
                      {count(p.voices, "voiceprint", "voiceprints")}
                    </span>
                  </span>
                </span>
                <span className={actions}>
                  <Button variant="outline" size="sm" onClick={() => setRenaming(p)}>
                    <Pencil /> Rename
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setForgetting(p)}
                    aria-label={`Forget ${p.name}`}
                  >
                    <Trash2 /> Forget
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {renaming ? (
        <NameDialog
          title="Rename this person"
          label="Their name"
          initial={renaming.name}
          onCancel={() => setRenaming(null)}
          onSubmit={(name) => {
            const p = renaming;
            setRenaming(null);
            void act(() => api.renamePerson(p.id, name.trim()), "They could not be renamed.");
          }}
        />
      ) : null}
      {forgetting ? (
        <ConfirmDialog
          title={`Forget ${forgetting.name}?`}
          confirmLabel="Forget"
          message="Every voiceprint of them is deleted, and later meetings will not suggest them. Their name stays in the meetings' transcripts as words. This cannot be undone."
          onCancel={() => setForgetting(null)}
          onConfirm={() => {
            const p = forgetting;
            setForgetting(null);
            void act(() => api.forgetPerson(p.id), "They could not be forgotten.");
          }}
        />
      ) : null}
    </div>
  );
}
