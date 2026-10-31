"use client";
// The left of the screen: every product as a tab, with arrow keys between them (a sheet under the stage on a
// phone, with the tabs as a dock). Ask and Add work now. The others say which step brings them and where the
// same thing is made today.
import type { CreativeApi, CreativeProject } from "@wasifyai/client";
import {
  Box,
  Image,
  LibraryBig,
  type LucideIcon,
  MessageCircle,
  Mic,
  Music,
  Type,
  Video,
} from "lucide-react";
import { Tabs } from "radix-ui";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChatScreen } from "../chat/ChatScreen";
import type { ChatToolResult } from "../chat/thread/use-thread-chat";
import { cn } from "../cn";
import { Button } from "../components/button";
import { Notice } from "../components/notice";
import { type Entry, coverOf, indexKindOf, toRow } from "../creations/model";
import { hint } from "../styles";
import type { EditorAssistant } from "../videobuilder/scenes/SceneEditor";
import { type ProjectCreations, entriesOf } from "./use-project-media";

export type CreativeAssistant = Omit<EditorAssistant, "model">;
export type CreativeScreen = "image" | "video" | "voice" | "music" | "titles" | "model3d";

type Waiting = { step: string; today: string };
const WAITING: Record<CreativeScreen, Waiting> = {
  image: { step: "Making a picture for a shot comes with the Shots step.", today: "Images" },
  video: { step: "Making a clip for a shot comes with the Shots step.", today: "Video" },
  voice: { step: "Voice comes with the Cut step.", today: "Speak" },
  music: { step: "Music for the cut comes with the Cut step.", today: "Music" },
  titles: { step: "Titles over the cut come with the Cut step.", today: "Motion graphics" },
  model3d: { step: "3D comes after the Cut step.", today: "3D models" },
};

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
const CHANGES_THE_PLAN = /^creative\.(edit_plan|undo)$/;

export function MakePanel({
  api,
  project,
  selected,
  selectedName,
  assistant,
  creations,
  added,
  problem,
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
  onAdd: (kind: string, id: string) => void;
  onOpenScreen?: (screen: CreativeScreen) => void;
  onChanged: (toolId: string, action: string) => void;
  onWorking: (working: boolean) => void;
  undoOfTool: (toolId: string) => { undone: boolean; undo: () => void } | null;
}) {
  const [tab, setTab] = useState<string>(assistant ? "ask" : "add");
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
      onValueChange={setTab}
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
      {(Object.keys(WAITING) as CreativeScreen[]).map((screen) => (
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
      <Tabs.Content value="add" className="min-h-0 flex-1 overflow-auto p-3">
        <AddTab
          creations={creations}
          added={added}
          problem={problem}
          selectedName={selectedName}
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

/** Pick from the library. File drop comes with the Shots step. */
function AddTab({
  creations,
  added,
  problem,
  selectedName,
  onAdd,
}: {
  creations?: ProjectCreations;
  added: Set<string>;
  problem: string | null;
  selectedName: string | null;
  onAdd: (kind: string, id: string) => void;
}) {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!creations) return;
    creations
      .recent()
      .then((recent) => setEntries(entriesOf(recent)))
      .catch(() => setFailed(true));
  }, [creations]);
  return (
    <div className="grid gap-3">
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
