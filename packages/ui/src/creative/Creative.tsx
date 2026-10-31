"use client";
// Creative Studio (ADR-0090): the projects, the brief of a new one, and one project's screen. At this stage a
// project ends at a plan of words; the Shots and Cut steps come in later stages and are shown switched off.
import type { CreativeApi, CreativeBrief, CreativeProject } from "@wasifyai/client";
import { Clapperboard, Plus, Trash2 } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Badge } from "../components/badge";
import { Button } from "../components/button";
import { ConfirmDialog } from "../components/dialog";
import { EmptyState } from "../components/empty-state";
import { Notice } from "../components/notice";
import { panel } from "../styles";
import { PageHeader, TopBarSlot } from "../window-bar";
import { BriefForm } from "./BriefForm";
import type { CreativeAssistant, CreativeScreen } from "./MakePanel";
import { ProjectView } from "./ProjectView";
import type { ProjectCreations } from "./use-project-media";

const POLL_LIST_MS = 3000;

export type CreativeSong = {
  id: string;
  title: string;
  seconds: number;
  lyrics: string;
  url: string;
};

export type CreativeProps = {
  api: CreativeApi;
  songs: () => Promise<CreativeSong[]>;
  /** the chat model button: the plan is written by the model the person chose */
  model?: ReactNode;
  onMakeSong?: () => void;
  /** a project to open at once, from the Library */
  open?: string | null;
  /** the Ask tab's assistant */
  assistant?: CreativeAssistant;
  /** the library, for the media rail and the Add tab */
  creations?: ProjectCreations;
  /** the screen where a tab that is still to come is made today */
  onOpenScreen?: (screen: CreativeScreen) => void;
};

type View = { at: "list" } | { at: "new" } | { at: "project"; id: string };

const STATUS: Record<CreativeProject["status"], string> = {
  draft: "Not planned yet",
  planning: "Planning",
  planned: "Planned",
  failed: "Did not finish",
  stopped: "Stopped",
  interrupted: "Stopped when the app closed",
};

export function Creative({
  api,
  songs,
  model,
  onMakeSong,
  open = null,
  assistant,
  creations,
  onOpenScreen,
}: CreativeProps) {
  const [view, setView] = useState<View>(open ? { at: "project", id: open } : { at: "list" });
  const [projects, setProjects] = useState<CreativeProject[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [gone, setGone] = useState<CreativeProject | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProjects(await api.list());
      setProblem(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "The engine did not answer.");
    }
  }, [api]);

  useEffect(() => {
    if (view.at !== "list") return;
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_LIST_MS);
    return () => clearInterval(timer);
  }, [view.at, refresh]);

  const start = async (title: string, brief: CreativeBrief) => {
    const made = await api.add(title, brief);
    await api.plan(made.id);
    setView({ at: "project", id: made.id });
  };

  if (view.at === "project") {
    return (
      <TopBarSlot>
        <div className="flex h-[calc(100dvh-3rem)] min-h-0 flex-col">
          <ProjectView
            api={api}
            songs={songs}
            id={view.id}
            model={model}
            assistant={assistant}
            creations={creations}
            onBack={() => setView({ at: "list" })}
            onMakeSong={onMakeSong}
            onOpenScreen={onOpenScreen}
          />
        </div>
      </TopBarSlot>
    );
  }

  return (
    <TopBarSlot>
      {model ? (
        <PageHeader className="flex h-14 shrink-0 items-center gap-4 border-b px-6 pt-1">
          <div className="flex min-w-0 items-center gap-2 ps-2 text-sm">{model}</div>
        </PageHeader>
      ) : null}
      <div className="mx-auto grid w-full max-w-5xl gap-5 p-[clamp(1rem,3vw,2rem)]">
        {view.at === "list" ? (
          <>
            <header className="flex flex-wrap items-start justify-between gap-3">
              <div className="grid gap-1.5">
                <h1 className="m-0 font-semibold text-xl">Creative Studio</h1>
                <p className="m-0 text-muted-foreground">
                  Turn a song and an idea into a plan of shots, cut on the beat, that you can
                  change. Nothing is drawn yet: this stage makes the plan.
                </p>
              </div>
              <Button type="button" onClick={() => setView({ at: "new" })}>
                <Plus aria-hidden /> New project
              </Button>
            </header>
            {problem ? (
              <Notice tone="error" title="Creative Studio could not be reached">
                {problem}
              </Notice>
            ) : null}
            {projects && projects.length === 0 ? (
              <EmptyState
                icon={Clapperboard}
                title="No projects yet"
                text="A project starts from a song in Your music and a line about what the video is."
                action={
                  <Button type="button" onClick={() => setView({ at: "new" })}>
                    New project
                  </Button>
                }
              />
            ) : null}
            <ul className="m-0 grid list-none gap-2 p-0">
              {(projects ?? []).map((p) => (
                <li key={p.id} className={`${panel} flex flex-wrap items-center gap-3`}>
                  <button
                    type="button"
                    className="grid min-w-0 flex-1 cursor-pointer gap-0.5 bg-transparent p-0 text-start"
                    onClick={() => setView({ at: "project", id: p.id })}
                  >
                    <span className="truncate font-semibold">{p.title}</span>
                    <span className="truncate text-muted-foreground text-sm">{p.brief.idea}</span>
                  </button>
                  <Badge variant={p.status === "planned" ? "secondary" : "outline"}>
                    {STATUS[p.status]}
                    {p.plan ? ` · ${p.plan.shots.length} shots` : ""}
                  </Badge>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete ${p.title}`}
                    onClick={() => setGone(p)}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        {view.at === "new" ? (
          <BriefForm
            api={api}
            songs={songs}
            onMakeSong={onMakeSong}
            onCancel={() => setView({ at: "list" })}
            submitLabel="Plan it"
            onSubmit={start}
          />
        ) : null}
      </div>
      {gone ? (
        <ConfirmDialog
          title={`Delete "${gone.title}"?`}
          message="The plan goes. The song stays in Your music."
          onCancel={() => setGone(null)}
          onConfirm={() => {
            const id = gone.id;
            setGone(null);
            void api.remove(id).then(refresh);
          }}
        />
      ) : null}
    </TopBarSlot>
  );
}
