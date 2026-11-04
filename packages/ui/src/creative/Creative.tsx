"use client";
// Creative Studio (ADR-0090): the projects, the brief of a new one, and one project's screen, which goes
// from the plan through the shots to the cut and the exported video.
import type { CreativeApi, CreativeBrief, CreativeProject } from "@wasifyai/client";
import { Clapperboard, Plus, Trash2 } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Badge } from "../components/badge";
import { Button } from "../components/button";
import { Checkbox } from "../components/checkbox";
import { ConfirmDialog } from "../components/dialog";
import { EmptyState } from "../components/empty-state";
import { Notice } from "../components/notice";
import { panel } from "../styles";
import { PageHeader, TopBarSlot } from "../window-bar";
import { BriefForm, type CreativeVoice } from "./BriefForm";
import type { AddedFile, CreativeAssistant, CreativeScreen, MakePanelMakers } from "./MakePanel";
import { ProjectView, picturesOf } from "./ProjectView";
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
  /** the person's saved voices, for a story's narrator and people */
  voices?: () => Promise<CreativeVoice[]>;
  /** the chat model button: the plan is written by the model the person chose */
  model?: ReactNode;
  /** the model button of a tab of the Make panel, when it is not the chat's */
  modelOfTab?: (tab: string) => ReactNode | undefined;
  /** the tabs of the Make panel that are made here, by the window that has the engine */
  makers?: MakePanelMakers;
  /** add a file of the person's to their library */
  addFile?: (file: File) => Promise<AddedFile>;
  /** Save a copy of a video kept in Your videos */
  saveVideo?: (videoId: string) => Promise<{ name: string; path: string }>;
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
  voices,
  model,
  modelOfTab,
  makers,
  addFile,
  saveVideo,
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
  const [withMade, setWithMade] = useState(false);

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
            voices={voices}
            id={view.id}
            model={model}
            modelOfTab={modelOfTab}
            makers={makers}
            addFile={addFile}
            saveVideo={saveVideo}
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
                  Turn a song or a story into a plan of shots, cut on the beat, that you can change,
                  then make the pictures and clips and export the finished video.
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
            voices={voices}
            onMakeSong={onMakeSong}
            pictures={picturesOf(creations)}
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
            setWithMade(false);
            void api.remove(id, withMade).then(refresh);
          }}
        >
          {Object.values(gone.shots?.takes ?? {}).some((t) => t.length > 0) ? (
            <Checkbox
              label="Also delete the pictures made for this project from your Library"
              checked={withMade}
              onCheckedChange={setWithMade}
            />
          ) : null}
        </ConfirmDialog>
      ) : null}
    </TopBarSlot>
  );
}
