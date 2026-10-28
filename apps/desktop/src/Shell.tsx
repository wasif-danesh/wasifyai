// SPDX-License-Identifier: AGPL-3.0-only
import type { ImageSummary, VideoSummary } from "@wasifyai/client";
import {
  AppBar,
  ApprovalCards,
  AudiobookPage,
  type CreationEntry,
  type CreationUse,
  DubPage,
  ElicitationCards,
  JobTray,
  LipSyncPage,
  LyricsPage,
  MusicPage,
  SearchPalette,
  SpeakPage,
  ToolPage,
  TranscribePage,
  type TrayJob,
  VoicesPage,
  WindowBarProvider,
  cn,
  jobLabel,
  openInMusic,
  placesOf,
  presetOf,
  sendToTool,
} from "@wasifyai/ui";
import { ArrowLeft, ArrowRight, PanelLeft } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Sidebar } from "./Sidebar";
import { client, connectionsApi, creationsApi, externalApi, voiceApi } from "./api";
import { resolveItem, titleFor } from "./menu";
import { CreatePage } from "./pages/Create";
import { CreationsPage, navFor, toolFor } from "./pages/Creations";
import { HomePage } from "./pages/Home";
import { Model3dPage } from "./pages/Model3d";
import { ModelsPage } from "./pages/Models";
import { NotebookPage } from "./pages/Notebook";
import { NotebooksPage } from "./pages/Notebooks";
import { SettingsPage } from "./pages/Settings";
import { TrainPage } from "./pages/Train";
import { VideoPage } from "./pages/Video";
import { VideoBuilderPage } from "./pages/VideoBuilder";
import { remembered } from "./remember";
import { useHistoryButtons, useRoute } from "./router";
import { videos } from "./videos";

const COLLAPSED_KEY = "wasifyai:sidebar-collapsed";

// the overlay title bar (and its traffic lights) exists on macOS only
const MAC = typeof navigator !== "undefined" && /Mac/.test(navigator.userAgent);

function Tool({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="grid size-7 place-items-center rounded-md text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/**
 * The running jobs of this window's engine, for the tray: what each is doing, and Stop where it can be. A clip
 * made on the Video screen is a run, not an action, so the clips being made are listed too, by their words.
 */
async function runningJobs(): Promise<TrayJob[]> {
  const [{ jobs }, clips] = await Promise.all([
    connectionsApi.jobs(),
    videos
      .list({ limit: 5, status: "working" })
      .then((p) => p.videos)
      .catch(() => []),
  ]);
  // a clip an agent asked for is already listed as its action
  const asAction = jobs.some((j) => j.action_id.startsWith("video."));
  const making: TrayJob[] = asAction
    ? []
    : clips.map((v) => ({ id: v.id, label: `Making your video: ${v.prompt}` }));
  return [
    ...making,
    ...jobs.map((j) => ({
      id: j.job_id,
      label: jobLabel(j.action_id),
      from: j.from,
      seconds: j.seconds,
      onStop: j.cancellable
        ? async () => {
            await connectionsApi.cancelJob(j.job_id);
          }
        : undefined,
    })),
  ];
}

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

/** The window once the engine is ready: the side menu and the screen it points at. */
export function Shell() {
  const {
    route,
    go,
    conversation: conversationId,
    key: chatKey,
    adopt,
    notebook,
    adoptNotebook,
  } = useRoute();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const history = useHistoryButtons();
  // the top bar of the window: where a screen's header goes, and whether one has taken it
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const [claims, setClaims] = useState(0);
  const bar = useMemo(
    () =>
      slot
        ? {
            target: slot,
            claim: () => {
              setClaims((n) => n + 1);
              return () => setClaims((n) => n - 1);
            },
          }
        : null,
    [slot],
  );
  // what every voice screen is given: this window's engine, its remembered choices, its navigation
  const voice = { api: voiceApi, runs: client, remembered, go, place: "device" as const };
  // an image whose recipe was sent to Create ("make it again"); used once, then forgotten
  const [again, setAgain] = useState<ImageSummary | null>(null);
  // a result sent to Edit as its source picture ("Edit this result")
  const [editSource, setEditSource] = useState<{ url: string; name: string; id?: string } | null>(
    null,
  );
  // a picture sent to Video's Animate ("Animate this"), and a clip sent to Extend ("Extend this")
  const [animateSource, setAnimateSource] = useState<{
    url: string;
    name: string;
    id?: string;
  } | null>(null);
  const [extendSource, setExtendSource] = useState<VideoSummary | null>(null);
  useEffect(() => {
    if (route !== "create") setAgain(null);
    if (route !== "edit") setEditSource(null);
    if (route !== "animate") setAnimateSource(null);
    if (route !== "extend") setExtendSource(null);
  }, [route]);
  // the Library's detail view hands an entry to a tool: the same hand-offs the make screens use (ADR-0093, U8)
  const handOff = useCallback(
    (entry: CreationEntry, action: CreationUse) => {
      const to = toolFor(entry, action);
      if (!to) return;
      if (entry.kind === "image") {
        const picture = { url: entry.image.image_url, name: `${entry.id}.png`, id: entry.id };
        if (action === "edit") setEditSource(picture);
        if (action === "animate") setAnimateSource(picture);
        if (action === "again") setAgain(entry.image);
      }
      if (entry.kind === "video" && action === "extend") setExtendSource(entry.video);
      if (entry.kind === "song" && action === "again") openInMusic(remembered, "again", entry.id);
      if (action === "split" || action === "convert" || action === "speechedit") {
        sendToTool(remembered, {
          kind: entry.kind === "speech" ? "speech" : "track",
          id: entry.id,
        });
      }
      go(to);
    },
    [go],
  );
  const animateThis = useCallback(
    (image: ImageSummary) => {
      setAnimateSource({ url: image.image_url, name: `${image.id}.png`, id: image.id });
      go("animate");
    },
    [go],
  );
  const extendThis = useCallback(
    (video: VideoSummary) => {
      setExtendSource(video);
      go("extend");
    },
    [go],
  );
  // a notebook has three panes: on a window too narrow for them and the menu, the menu steps aside
  // (until the person opens it; this is not remembered)
  const stepped = useRef(false);
  useEffect(() => {
    if (route === "notebook" && window.innerWidth < 1280) {
      setCollapsed((was) => {
        stepped.current = !was; // only a menu this effect closed is opened again on leaving
        return true;
      });
    } else if (stepped.current) {
      stepped.current = false;
      setCollapsed(false);
    }
  }, [route]);
  // the one search (⌘K and the bar's button): any tool by name, or a creation by what it is about
  const [searching, setSearching] = useState(false);
  const openSearch = useCallback(() => setSearching(true), []);
  const resolve = useMemo(
    () => resolveItem(route, go, { conversationId, notebook }),
    [route, go, conversationId, notebook],
  );
  const title = useMemo(() => titleFor(resolve, route), [resolve, route]);
  const places = useMemo(
    () => [
      ...placesOf(resolve).flatMap((p) =>
        p.view.onSelect ? [{ id: p.id, label: p.label, onSelect: p.view.onSelect }] : [],
      ),
      { id: "settings", label: "Settings", onSelect: () => go("settings") },
    ],
    [resolve, go],
  );
  const set = (v: boolean) => {
    setCollapsed(v);
    try {
      localStorage.setItem(COLLAPSED_KEY, v ? "1" : "0");
    } catch {
      // the menu still works; it just forgets
    }
  };

  return (
    <WindowBarProvider bar={bar}>
      <div
        data-menu-collapsed={collapsed}
        className="flex h-dvh flex-col overflow-hidden bg-background text-foreground"
      >
        <ApprovalCards api={connectionsApi} />
        <ElicitationCards external={externalApi} connections={connectionsApi} />
        <AppBar
          drag
          navClassName={cn(
            "gap-0.5 pe-1",
            MAC ? "ps-[84px]" : "ps-3",
            !collapsed && "w-64 border-e",
          )}
          nav={
            <>
              <Tool label="Back" disabled={!history.back} onClick={() => window.history.back()}>
                <ArrowLeft className="size-4" />
              </Tool>
              <Tool
                label="Forward"
                disabled={!history.forward}
                onClick={() => window.history.forward()}
              >
                <ArrowRight className="size-4" />
              </Tool>
              <Tool
                label={collapsed ? "Show the side menu" : "Hide the side menu"}
                onClick={() => set(!collapsed)}
              >
                <PanelLeft className="size-4" />
              </Tool>
            </>
          }
          title={title}
          showTitle={claims === 0}
          slot={setSlot}
          tray={<JobTray load={runningJobs} />}
          onSearch={openSearch}
        />
        <SearchPalette
          open={searching}
          onClose={() => setSearching(false)}
          places={places}
          creations={creationsApi}
          onOpenCreation={(entry) => navFor(go).open(entry)}
        />
        <div className="flex min-h-0 flex-1">
          {collapsed ? null : (
            <Sidebar route={route} go={go} conversationId={conversationId} notebook={notebook} />
          )}
          <div className="relative flex min-w-0 flex-1 flex-col">
            <main id="main" className="min-h-0 flex-1 overflow-auto">
              {route === "home" ? (
                <HomePage key={chatKey} go={go} conversationId={conversationId} onAdopt={adopt} />
              ) : null}
              {route === "create" ? (
                <CreatePage
                  key={`create-${again?.id ?? ""}`}
                  mode="text"
                  go={go}
                  preset={again ? presetOf(again) : null}
                  onEditThis={(image) => {
                    setEditSource({ url: image.image_url, name: `${image.id}.png`, id: image.id });
                    go("edit");
                  }}
                  onAnimateThis={animateThis}
                />
              ) : null}
              {route === "edit" ? (
                <CreatePage
                  key={`edit-${editSource?.url ?? ""}`}
                  mode="image"
                  go={go}
                  source={editSource}
                  onAnimateThis={animateThis}
                />
              ) : null}
              {route === "reference" ? (
                <CreatePage mode="reference" go={go} onAnimateThis={animateThis} />
              ) : null}
              {route === "inpaint" ? (
                <CreatePage mode="inpaint" go={go} onAnimateThis={animateThis} />
              ) : null}
              {route === "creations" ? <CreationsPage go={go} handOff={handOff} /> : null}
              {/* the routes that were "Your images", "Your videos" and "Your music" (ADR-0093, U8) */}
              {route === "library" ? (
                <CreationsPage go={go} handOff={handOff} filter="images" />
              ) : null}
              {route === "videos" ? (
                <CreationsPage go={go} handOff={handOff} filter="videos" />
              ) : null}
              {route === "tracks" ? (
                <CreationsPage go={go} handOff={handOff} filter="songs" />
              ) : null}
              {route === "notebooks" ? <NotebooksPage /> : null}
              {route === "notebook" && notebook ? (
                <NotebookPage
                  key={`notebook-${chatKey}`}
                  notebook={notebook}
                  onAdopt={adoptNotebook}
                />
              ) : null}
              {route === "speak" ? <SpeakPage {...voice} /> : null}
              {route === "transcribe" ? <TranscribePage {...voice} /> : null}
              {route === "voices" ? <VoicesPage {...voice} /> : null}
              {route === "music" ? <MusicPage {...voice} /> : null}
              {route === "lyrics" ? <LyricsPage {...voice} /> : null}
              {route === "lipsync" ? <LipSyncPage {...voice} /> : null}
              {route === "audiobook" ? <AudiobookPage {...voice} /> : null}
              {route === "dub" ? <DubPage {...voice} /> : null}
              {route === "separate" ? <ToolPage tool="separate" {...voice} /> : null}
              {route === "convert" ? <ToolPage tool="convert" {...voice} /> : null}
              {route === "speechedit" ? <ToolPage tool="edit" {...voice} /> : null}
              {route === "video" ? (
                <VideoPage mode="text" go={go} onExtendThis={extendThis} />
              ) : null}
              {route === "animate" ? (
                <VideoPage
                  key={`animate-${animateSource?.url ?? ""}`}
                  mode="image"
                  go={go}
                  onExtendThis={extendThis}
                  sourceImage={animateSource}
                />
              ) : null}
              {route === "extend" ? (
                <VideoPage
                  key={`extend-${extendSource?.id ?? ""}`}
                  mode="extend"
                  go={go}
                  sourceVideo={extendSource}
                />
              ) : null}
              {route === "videobuilder" ? <VideoBuilderPage go={go} /> : null}
              {route === "model3d" ? <Model3dPage go={go} /> : null}
              {route === "train" ? <TrainPage go={go} /> : null}
              {route === "models" ? <ModelsPage /> : null}
              {route === "settings" ? <SettingsPage /> : null}
            </main>
          </div>
        </div>
      </div>
    </WindowBarProvider>
  );
}
