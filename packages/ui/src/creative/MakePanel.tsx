"use client";
// The left of the screen: every product as a tab, with arrow keys between them (a sheet under the stage on a
// phone, with the tabs as a dock). Image and Video make a version of the shot that is selected; Music makes a song
// for the project's media; Voice and Titles are the cut's captions and titles; Add and Ask work on the project.
// 3D says where the same thing is made today.
import type { CreativeApi, CreativeProject, CutEdit, CutState } from "@wasifyai/client";
import {
  Box,
  Image,
  LibraryBig,
  type LucideIcon,
  MessageCircle,
  Mic,
  Music,
  Type,
  Upload,
  Video,
} from "lucide-react";
import { Tabs } from "radix-ui";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { ChatScreen } from "../chat/ChatScreen";
import type { ChatToolResult } from "../chat/thread/use-thread-chat";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { Segmented } from "../components/segmented";
import { type Entry, coverOf, indexKindOf, toRow } from "../creations/model";
import { hint } from "../styles";
import type { EditorAssistant } from "../videobuilder/scenes/SceneEditor";
import { CaptionsTab, TitlesTab } from "./CutTabs";
import { type ProjectCreations, entriesOf } from "./use-project-media";

export type CreativeAssistant = Omit<EditorAssistant, "model">;
export type CreativeScreen = "image" | "video" | "voice" | "music" | "titles" | "model3d";
/** A file of the person's, now in their library. */
export type AddedFile = { kind: string; id: string };

type Waiting = { step: string; today: string };
const WAITING: Record<CreativeScreen, Waiting> = {
  image: { step: "Making a picture for a shot comes with the Shots step.", today: "Images" },
  video: { step: "Making a clip for a shot comes with the Shots step.", today: "Video" },
  voice: { step: "Captions from the singing come once there is a plan.", today: "Speak" },
  music: { step: "Making a song here comes with the app's Music screen.", today: "Music" },
  titles: { step: "Titles over the cut come once there is a plan.", today: "Motion graphics" },
  model3d: { step: "3D comes after the Cut step.", today: "3D models" },
};

/** The tabs made here. The window has the engine and the models, so it draws them; what they make is handed over. */
export type MakePanelMakers = Partial<
  Record<
    "image" | "video" | "music" | "voice",
    (onMade: (id: string, kind?: string) => void) => ReactNode
  >
>;

/** The cut, for the Voice and Titles tabs. */
export type PanelCut = {
  state: CutState;
  /** whether the times of the song's words are known */
  timed: boolean;
  busy: boolean;
  edit: (edits: CutEdit[]) => void;
  /** where the video is playing now */
  at: () => number;
};

const MADE_LINE: Record<"image" | "video" | "music" | "voice", (name: string | null) => string> = {
  image: (name) =>
    name
      ? `What you make here is a version of ${name}.`
      : "Select a shot to make a version for it. Otherwise it joins this project's media.",
  video: (name) =>
    name
      ? `What you make here is a version of ${name}.`
      : "Select a shot to make a version for it. Otherwise it joins this project's media.",
  music: () =>
    "What you make here joins this project's media. The video's song is the one in the brief.",
  voice: () =>
    "What you say here joins this project's media. A story's reading is made by its plan.",
};
const KIND_OF = { image: "image", video: "video", music: "track", voice: "speech" } as const;

const TABS: { id: CreativeScreen | "add" | "ask"; label: string; icon: LucideIcon }[] = [
  { id: "image", label: "Image", icon: Image },
  { id: "video", label: "Video", icon: Video },
  { id: "voice", label: "Voice", icon: Mic },
  { id: "music", label: "Music", icon: Music },
  { id: "titles", label: "Titles", icon: Type },
  { id: "model3d", label: "3D", icon: Box },
  { id: "add", label: "Add", icon: LibraryBig },
  { id: "ask", label: "Ask", icon: MessageCircle },
];

const SUGGESTIONS = [
  "Make this shot animate",
  "Make the first part calmer",
  "Remove the last shot",
  "Change the place of this shot",
];
const CHANGES_THE_PLAN =
  /^creative\.(edit_plan|undo|redo_shot|make_shots|choose_take|edit_cut|cut|export)$/;

export function MakePanel({
  api,
  project,
  selected,
  selectedName,
  assistant,
  creations,
  added,
  problem,
  tab,
  onTab,
  makers,
  cut,
  addFile,
  onAdd,
  onOpenScreen,
  onChanged,
  onWorking,
  undoOfTool,
}: {
  api: CreativeApi;
  project: CreativeProject;
  selected: string | null;
  selectedName: string | null;
  assistant?: CreativeAssistant;
  creations?: ProjectCreations;
  /** what is already part of the project, as kind:id */
  added: Set<string>;
  problem: string | null;
  tab: string;
  onTab: (tab: string) => void;
  makers?: MakePanelMakers;
  cut?: PanelCut | null;
  addFile?: (file: File) => Promise<AddedFile>;
  onAdd: (kind: string, id: string) => void;
  onOpenScreen?: (screen: CreativeScreen) => void;
  onChanged: (toolId: string, action: string) => void;
  onWorking: (working: boolean) => void;
  undoOfTool: (toolId: string) => { undone: boolean; undo: () => void } | null;
}) {
  const [conversation, setConversation] = useState(project.conversation_id ?? null);
  const projectId = project.id;
  const keepConversation = useCallback(
    (id: string) => {
      setConversation((known) => {
        if (known !== id) void api.keepConversation(projectId, id).catch(() => {});
        return id;
      });
    },
    [api, projectId],
  );
  const workingOn = useMemo(
    () => ({
      working_on: {
        action_id: "creative.read_project",
        params: { project_id: projectId, shot_id: selected || undefined },
      },
    }),
    [projectId, selected],
  );
  const onToolResult = useCallback(
    (result: ChatToolResult) => {
      const action = String(result.output?.action_id ?? "");
      if (result.status === "ok" && CHANGES_THE_PLAN.test(action)) onChanged(result.id, action);
    },
    [onChanged],
  );

  return (
    <Tabs.Root
      value={tab}
      onValueChange={onTab}
      className="flex h-[34rem] min-h-0 flex-col @4xl:h-full"
    >
      <Tabs.List
        aria-label="Make something for this project"
        className="order-last flex shrink-0 gap-1 overflow-x-auto border-t p-1.5 @4xl:order-none @4xl:grid @4xl:grid-cols-4 @4xl:overflow-x-visible @4xl:border-t-0 @4xl:border-b"
      >
        {TABS.map(({ id, label, icon: Icon }) => (
          <Tabs.Trigger
            key={id}
            value={id}
            className="grid min-w-10 flex-1 cursor-pointer justify-items-center gap-0.5 rounded-md py-1.5 text-muted-foreground text-xs outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 data-[state=active]:bg-muted data-[state=active]:font-medium data-[state=active]:text-foreground"
          >
            <Icon aria-hidden className="size-4" />
            {label}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      {(["image", "video", "music", "voice"] as const).map((screen) => {
        const maker = makers?.[screen];
        if (!maker) return null;
        // the Voice tab shows the captions of the cut instead, once there is one
        if (screen === "voice" && cut) return null;
        return (
          // kept while another tab shows: a picture being made must not be stopped by a click
          <Tabs.Content
            key={screen}
            value={screen}
            forceMount
            hidden={tab !== screen}
            className={cn("min-h-0 flex-1 flex-col", tab === screen ? "flex" : "hidden")}
          >
            <p className={`${hint} m-0 border-b px-3 py-1.5`}>{MADE_LINE[screen](selectedName)}</p>
            {maker((id, kind) => onAdd(kind ?? KIND_OF[screen], id))}
          </Tabs.Content>
        );
      })}
      {(Object.keys(WAITING) as CreativeScreen[])
        .filter((screen) =>
          screen === "image" || screen === "video" || screen === "music"
            ? !makers?.[screen]
            : screen === "voice"
              ? !cut && !makers?.voice
              : screen === "titles"
                ? !cut
                : true,
        )
        .map((screen) => (
          <Tabs.Content key={screen} value={screen} className="min-h-0 flex-1 overflow-auto p-3">
            <div className="grid gap-3">
              <p className="m-0 text-sm">{WAITING[screen].step}</p>
              <p className={`${hint} m-0`}>
                Today it is made in {WAITING[screen].today}. Then bring it here with Add.
              </p>
              {onOpenScreen ? (
                <Button type="button" variant="outline" onClick={() => onOpenScreen(screen)}>
                  Open {WAITING[screen].today}
                </Button>
              ) : null}
            </div>
          </Tabs.Content>
        ))}
      {cut ? (
        <>
          <Tabs.Content value="voice" className="min-h-0 flex-1 flex-col overflow-auto">
            <VoiceTab cut={cut} speak={makers?.voice} onAdd={onAdd} />
          </Tabs.Content>
          <Tabs.Content value="titles" className="min-h-0 flex-1 overflow-auto p-3">
            <TitlesTab cut={cut.state} busy={cut.busy} edit={cut.edit} at={cut.at} />
          </Tabs.Content>
        </>
      ) : null}
      <Tabs.Content value="add" className="min-h-0 flex-1 overflow-auto p-3">
        <AddTab
          creations={creations}
          added={added}
          problem={problem}
          selectedName={selectedName}
          addFile={addFile}
          onAdd={onAdd}
        />
      </Tabs.Content>
      {assistant ? (
        // kept while another tab shows: a chat that is working must not be stopped by a click
        <Tabs.Content
          value="ask"
          forceMount
          hidden={tab !== "ask"}
          className={cn("min-h-0 flex-1 flex-col", tab === "ask" ? "flex" : "hidden")}
        >
          {selectedName ? (
            <p className={`${hint} m-0 border-b px-3 py-1.5`}>Working on {selectedName}.</p>
          ) : null}
          <div className="min-h-0 flex-1">
            <ChatScreen
              runs={assistant.runs}
              assistant={assistant.api}
              images={assistant.images}
              tracks={assistant.tracks}
              notices={assistant.notices}
              blockedReason={assistant.blockedReason}
              onNeedModel={assistant.onNeedModel}
              onOpenSettings={assistant.onOpenSettings}
              examples={SUGGESTIONS}
              conversationId={conversation}
              onConversation={keepConversation}
              runInput={workingOn}
              onToolResult={onToolResult}
              onWorking={onWorking}
              undoOfTool={undoOfTool}
            />
          </div>
        </Tabs.Content>
      ) : null}
    </Tabs.Root>
  );
}

/** The captions of the cut, and saying a line in a voice: a narration or a spoken line for the project. */
function VoiceTab({
  cut,
  speak,
  onAdd,
}: {
  cut: PanelCut;
  speak?: (onMade: (id: string, kind?: string) => void) => ReactNode;
  onAdd: (kind: string, id: string) => void;
}) {
  const [part, setPart] = useState<"captions" | "speak">("captions");
  return (
    <>
      {speak ? (
        <div className="border-b p-2">
          <Segmented
            label="Voice"
            size="sm"
            value={part}
            onValueChange={(v) => setPart(v as "captions" | "speak")}
            options={[
              { value: "captions", label: "Captions" },
              { value: "speak", label: "Speak" },
            ]}
          />
        </div>
      ) : null}
      {part === "speak" && speak ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <p className={`${hint} m-0 border-b px-3 py-1.5`}>{MADE_LINE.voice(null)}</p>
          {speak((id, kind) => onAdd(kind ?? "speech", id))}
        </div>
      ) : (
        <div className="p-3">
          <CaptionsTab cut={cut.state} timed={cut.timed} busy={cut.busy} edit={cut.edit} />
        </div>
      )}
    </>
  );
}

/** Pick from the library, or drop a file of your own, which then lives in the library too. */
function AddTab({
  creations,
  added,
  problem,
  selectedName,
  addFile,
  onAdd,
}: {
  creations?: ProjectCreations;
  added: Set<string>;
  problem: string | null;
  selectedName: string | null;
  addFile?: (file: File) => Promise<AddedFile>;
  onAdd: (kind: string, id: string) => void;
}) {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [over, setOver] = useState(false);
  const [adding, setAdding] = useState(0);
  const [refused, setRefused] = useState<string | null>(null);
  const read = useCallback(() => {
    if (!creations) return;
    creations
      .recent()
      .then((recent) => setEntries(entriesOf(recent)))
      .catch(() => setFailed(true));
  }, [creations]);
  useEffect(() => read(), [read]);
  const take = async (files: Iterable<File>) => {
    if (!addFile) return;
    setRefused(null);
    for (const file of files) {
      setAdding((n) => n + 1);
      try {
        const made = await addFile(file);
        onAdd(made.kind, made.id);
      } catch (e) {
        setRefused(`${file.name}: ${e instanceof Error ? e.message : "it could not be added."}`);
      } finally {
        setAdding((n) => n - 1);
      }
    }
    read();
  };
  return (
    <div className="grid gap-3">
      {addFile ? (
        <label
          data-slot="drop-files"
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            void take(Array.from(e.dataTransfer.files));
          }}
          className={cn(
            "grid cursor-pointer place-items-center gap-1 rounded-md border-2 border-dashed p-4 text-center text-muted-foreground text-xs focus-within:ring-[3px] focus-within:ring-ring/50",
            over && "border-primary bg-primary/5 text-foreground",
          )}
        >
          <Upload aria-hidden className="size-4" />
          {adding ? "Adding…" : "Drop a picture, clip or sound here, or choose a file"}
          <input
            type="file"
            multiple
            accept=".png,.jpg,.jpeg,.webp,video/*,audio/*"
            aria-label="Choose a picture, clip or sound to add"
            className="sr-only"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              void take(files);
            }}
          />
        </label>
      ) : null}
      {refused ? (
        <Notice tone="error" title="It was not added">
          {refused}
        </Notice>
      ) : null}
      <p className={`${hint} m-0`}>
        From your Library{selectedName ? `, marked for ${selectedName}` : ""}. It is not copied.
      </p>
      {problem ? (
        <Notice tone="error" title="It was not added">
          {problem}
        </Notice>
      ) : null}
      {failed ? (
        <Notice tone="error" title="The Library could not be read">
          Try again in a moment.
        </Notice>
      ) : null}
      {entries && entries.length === 0 ? (
        <p className={`${hint} m-0`}>There is nothing in your Library yet.</p>
      ) : null}
      <ul className="m-0 grid list-none grid-cols-2 gap-2 p-0">
        {(entries ?? []).map((entry) => {
          const row = toRow(entry);
          const cover = coverOf(entry);
          const kind = indexKindOf(entry.kind);
          const there = added.has(`${kind}:${entry.id}`);
          return (
            <li key={row.key}>
              <button
                type="button"
                disabled={there}
                aria-label={there ? `Already added: ${row.title}` : `Add: ${row.title}`}
                onClick={() => onAdd(kind, entry.id)}
                className="grid w-full cursor-pointer gap-1 rounded-md border p-1 text-start outline-none hover:border-primary/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-default disabled:opacity-60"
              >
                {cover ? (
                  <img src={cover} alt="" className="aspect-video w-full rounded object-cover" />
                ) : (
                  <span className="grid aspect-video w-full place-items-center rounded bg-muted text-muted-foreground text-xs">
                    {row.kindLabel}
                  </span>
                )}
                <span className="truncate text-xs">{row.title}</span>
                {there ? <span className="text-muted-foreground text-xs">Added</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
