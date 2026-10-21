"use client";

import type {
  AskedMessage,
  NotebookCitation,
  NotebookConversationSummary,
  NotebookSource,
  NotebooksApi,
  RunClient,
} from "@wasifyai/client";
import { isWorking } from "@wasifyai/client";
import { Plus } from "lucide-react";
import {
  type CSSProperties,
  type ReactNode,
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { cn } from "../cn";
import { Button } from "../components/button";
import { AddSources } from "./AddSources";
import { SourceGuide } from "./SourceGuide";
import { type Highlight, SourceViewer } from "./SourceViewer";
import { SourcesPane } from "./SourcesPane";
import { StudioPane } from "./StudioPane";
import { noReadySourceReason, scopeIds, scopeLabel } from "./scope";
import { useGuide } from "./use-guide";
import { useNotebookChat } from "./use-notebook-chat";
import { useNotebookSources } from "./use-notebook-sources";
import { useStudioWidth } from "./use-studio-width";

// the chat on assistant-ui (ADR-0082) is a separate chunk, so the notebook's lists and sources show before it arrives
const NotebookChat = lazy(() =>
  import("./NotebookChat").then((m) => ({ default: m.NotebookChat })),
);

type PaneName = "sources" | "chat" | "studio";

export type NotebookWorkspaceProps = {
  api: NotebooksApi;
  runs: Pick<RunClient, "startRun" | "watchRun">;
  /** null: a draft, saved when its first source is added or its title is set */
  notebookId: string | null;
  title: string;
  onTitle: (title: string) => void;
  /** Save the draft and give back its id (called once a source is added). */
  ensureNotebook: () => Promise<string>;
  /** Setup notices: the search model or the reader is missing. */
  notices?: ReactNode;
  /** The search model is on this computer. Without it nothing can be read or asked. */
  searchReady: boolean;
  /** The model chip next to the box (the chosen chat model). */
  chip?: ReactNode;
  /** Whether a chat model is chosen (null while unknown). */
  chatModelChosen?: boolean | null;
  onNeedModel?: () => void;
  /** A note about the first source of a draft (set by the page when it saves). */
  onBack?: () => void;
  /** A fresh link to a picture of the image product (an infographic). */
  imageUrl?: (id: string) => Promise<string>;
  /** Save a picture of the library into the person's folder (the desktop window; the web leaves it out). */
  saveImage?: (imageId: string, path?: string) => Promise<{ name: string; path?: string }>;
};

/**
 * One notebook: sources on the left, the conversation in the middle, Studio on the right; tabs
 * instead on a narrow window. A new notebook opens on the add-sources screen.
 */
export function NotebookWorkspace(props: NotebookWorkspaceProps) {
  const { api, runs, notebookId, title, onTitle, ensureNotebook, searchReady } = props;
  const src = useNotebookSources({ api, notebookId, ensureNotebook });
  const [unticked, setUnticked] = useState<Set<string>>(() => new Set());
  const [pane, setPane] = useState<PaneName>("chat");
  const [adding, setAdding] = useState(false);
  const [viewing, setViewing] = useState<{ id: string; highlight: Highlight | null } | null>(null);
  const [seed, setSeed] = useState<{ text: string; id: number } | null>(null);
  const [kept, setKept] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<NotebookConversationSummary[]>([]);
  const [draftTitle, setDraftTitle] = useState(title);
  const studio = useStudioWidth();
  useEffect(() => setDraftTitle(title), [title]);

  const chat = useNotebookChat({
    runs,
    api,
    notebookId,
    conversationId,
    onConversation: (id) => {
      setConversationId(id);
      if (notebookId)
        api
          .conversations(notebookId)
          .then(setConversations)
          .catch(() => {});
    },
  });

  // reopen the notebook where it was left: its latest conversation
  useEffect(() => {
    setConversationId(null);
    setConversations([]);
    if (!notebookId) return;
    let gone = false;
    api
      .conversations(notebookId)
      .then((list) => {
        if (gone) return;
        setConversations(list);
        const first = list[0];
        if (first) setConversationId(first.id);
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [notebookId, api]);

  const ready = src.sources.filter((s) => s.status === "ready").length;
  const none = src.loaded && src.sources.length === 0;
  const scope = useMemo(() => scopeIds(src.sources, unticked), [src.sources, unticked]);
  const label = scopeLabel(src.sources, unticked);
  const everyTickedOff = scope !== undefined && scope.length === 0;
  const noReady = noReadySourceReason(src.sources);

  const blocked = !searchReady
    ? "Get the search model first (see Set up reading documents)."
    : props.chatModelChosen === false
      ? "Choose a chat model to ask questions."
      : none
        ? "Add a source first."
        : noReady !== null
          ? noReady
          : everyTickedOff
            ? "Tick at least one source."
            : null;

  // outputs need what questions need, except that no search model is needed (a long selection is
  // then cut to its starts) and a source being read is simply left out
  const studioBlocked =
    props.chatModelChosen === false
      ? "Choose a chat model to make things from your sources."
      : notebookId === null || none
        ? "Add a source first."
        : ready === 0
          ? (noReady ?? "Your sources are still being read.")
          : everyTickedOff
            ? "Tick at least one source."
            : null;

  const guide = useGuide(api, runs, notebookId, {
    canMake: studioBlocked === null && props.chatModelChosen !== false,
    readyCount: ready,
  });

  const saveNote = useCallback(
    async (m: AskedMessage) => {
      const at = chat.state.messages.findIndex((x) => x.id === m.id);
      const question =
        chat.state.messages
          .slice(0, Math.max(at, 0))
          .reverse()
          .find((x) => x.role === "user")?.text ?? "";
      const title = (question || "Answer").replace(/\s+/g, " ").trim().slice(0, 80);
      const cites = m.citations.map((c) => `[${c.n}] ${c.title}`).join("\n");
      const content = cites ? `${m.text}\n\nSources:\n${cites}` : m.text;
      const made = await src.addNote(title, content);
      if (made) {
        setKept("Saved as a note in your sources.");
        setTimeout(() => setKept(null), 3500);
      }
    },
    [chat.state.messages, src],
  );

  const open = useCallback((source: NotebookSource) => {
    setViewing({ id: source.id, highlight: null });
    setPane("sources");
  }, []);

  const openCitation = useCallback((c: NotebookCitation) => {
    setViewing({
      id: c.document_id,
      highlight: { start: c.start_line, end: c.end_line, snapshot: c.text },
    });
    setPane("sources");
  }, []);

  const addFiles = useCallback(
    async (files: File[]) => {
      setAdding(false);
      await src.upload(files);
    },
    [src],
  );
  const addNote = useCallback(
    async (noteTitle: string, content: string) => {
      setAdding(false);
      await src.addNote(noteTitle, content);
    },
    [src],
  );

  const adder = (
    <AddSources
      heading={notebookId === null || none ? "Let’s start your notebook" : "Add sources"}
      busy={src.busy}
      onFiles={(f) => void addFiles(f)}
      onNote={(t, c) => void addNote(t, c)}
      onClose={none ? undefined : () => setAdding(false)}
      className="w-full max-w-xl"
    />
  );

  // nothing to ask yet: the add-sources screen takes the middle, with what must be set up under it
  const showAdder = notebookId === null || none;

  const tab = (name: PaneName, text: string) => (
    <button
      key={name}
      type="button"
      aria-pressed={pane === name}
      onClick={() => setPane(name)}
      className={cn(
        "flex-1 rounded-full px-3 py-1.5 text-sm",
        pane === name ? "bg-accent font-medium" : "text-muted-foreground",
      )}
    >
      {text}
    </button>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header
        data-tauri-drag-region
        className="flex h-14 shrink-0 items-center gap-3 border-b px-5 pt-1 [[data-menu-collapsed=true]_&]:ps-32"
      >
        {props.onBack ? (
          <Button type="button" variant="ghost" size="sm" onClick={props.onBack}>
            Notebooks
          </Button>
        ) : null}
        <input
          aria-label="Notebook name"
          value={draftTitle}
          maxLength={200}
          onChange={(e) => setDraftTitle(e.target.value)}
          onBlur={() => {
            const next = draftTitle.trim();
            if (next && next !== title) onTitle(next);
            else setDraftTitle(title);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          className="min-w-0 flex-1 truncate rounded-md bg-transparent px-2 py-1 font-medium text-lg outline-none hover:bg-accent focus:bg-accent"
        />
        <span className="hidden text-muted-foreground text-sm sm:inline">{label}</span>
      </header>

      <div className="flex shrink-0 gap-1 border-b p-2 lg:hidden" role="tablist" aria-label="Panes">
        {tab("sources", "Sources")}
        {tab("chat", "Chat")}
        {tab("studio", "Studio")}
      </div>

      <div
        ref={studio.grid}
        className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] lg:grid-cols-[19rem_minmax(0,1fr)_var(--studio-width,17rem)] xl:grid-cols-[21rem_minmax(0,1fr)_var(--studio-width,19rem)]"
        style={
          studio.width === null
            ? undefined
            : ({ "--studio-width": `${studio.width}px` } as CSSProperties)
        }
      >
        <div className={cn("min-h-0 border-e", pane !== "sources" && "hidden lg:block")}>
          {viewing && notebookId ? (
            <SourceViewer
              api={api}
              notebookId={notebookId}
              sourceId={viewing.id}
              highlight={viewing.highlight}
              onBack={() => setViewing(null)}
              onChanged={() => void src.refresh()}
            />
          ) : (
            <SourcesPane
              sources={src.sources}
              folders={src.folders}
              unticked={unticked}
              onUnticked={setUnticked}
              onOpen={open}
              onAdd={() => setAdding(true)}
              onNewFolder={(name) => void src.createFolder(name)}
              onRename={(s, t) => void src.rename(s.id, t)}
              onRemove={(s) => void src.remove(s.id)}
              onRetry={(s) => void src.retry(s.id)}
              onCancel={(s) => void src.cancel(s.id)}
              onMove={(s, f) => void src.move([s.id], f)}
              onRenameFolder={(f, n) => void src.renameFolder(f.id, n)}
              onRemoveFolder={(f) => void src.removeFolder(f.id)}
            />
          )}
        </div>

        <div className={cn("relative min-h-0", pane !== "chat" && "hidden lg:block")}>
          {kept ? <output className="block px-5 pt-3 text-ok text-sm">{kept}</output> : null}
          {src.problem || src.rejected.length ? (
            <div className="px-5 pt-3">
              {src.problem ? (
                <p role="alert" className="text-destructive text-sm">
                  {src.problem}
                </p>
              ) : null}
              {src.rejected.map((r) => (
                <p key={r.name} role="alert" className="text-destructive text-sm">
                  {r.name}: {r.reason}
                </p>
              ))}
            </div>
          ) : null}
          <Suspense fallback={null}>
            <NotebookChat
              state={chat.state}
              onSend={(text) => void chat.send(text, scope)}
              onStop={chat.stop}
              onRetry={chat.retry}
              onOpenCitation={openCitation}
              scope={label}
              blockedReason={blocked}
              notices={showAdder ? undefined : props.notices}
              chip={props.chip}
              onNeedModel={props.onNeedModel}
              onSaveNote={(m) => void saveNote(m)}
              draftSeed={seed}
              guide={
                <SourceGuide
                  state={guide.state}
                  making={guide.making}
                  problem={guide.problem}
                  onMake={() => void guide.make()}
                  onAsk={(q) => setSeed({ text: q, id: Date.now() })}
                />
              }
              empty={
                showAdder ? (
                  <div className="grid w-full max-w-xl gap-4">
                    {adder}
                    {props.notices}
                  </div>
                ) : undefined
              }
              header={
                conversations.length > 0 || chat.state.messages.length > 0 ? (
                  <>
                    {conversations.length > 1 ? (
                      <select
                        aria-label="Conversation"
                        className="h-8 max-w-48 rounded-md border bg-background px-2 text-sm"
                        value={conversationId ?? ""}
                        onChange={(e) => {
                          chat.reset();
                          setConversationId(e.target.value || null);
                        }}
                      >
                        {conversations.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.title || "Conversation"}
                          </option>
                        ))}
                      </select>
                    ) : null}
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={isWorking(chat.state)}
                      onClick={() => {
                        chat.reset();
                        setConversationId(null);
                      }}
                    >
                      <Plus /> New chat
                    </Button>
                  </>
                ) : undefined
              }
            />
          </Suspense>
          {adding && !none && notebookId !== null ? (
            <div className="absolute inset-0 z-10 grid place-items-center bg-background/80 p-6 backdrop-blur-sm">
              {adder}
            </div>
          ) : null}
        </div>

        <div
          ref={studio.column}
          className={cn("relative min-h-0 border-s", pane !== "studio" && "hidden lg:block")}
        >
          {/* drag this edge, or use the arrow keys, to make the Studio wider or narrower */}
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the Studio"
            aria-valuemin={studio.min}
            aria-valuemax={studio.max()}
            aria-valuenow={studio.width ?? undefined}
            tabIndex={0}
            title="Drag to resize; double-click to widen"
            className="absolute inset-y-0 -start-1 z-20 hidden w-2 cursor-col-resize touch-none outline-none hover:bg-primary/30 focus-visible:bg-primary/40 lg:block"
            {...studio.handle}
          />
          <StudioPane
            api={api}
            runs={runs}
            notebookId={notebookId}
            documentIds={scope}
            scopeLabel={label}
            blockedReason={studioBlocked}
            imageUrl={props.imageUrl}
            saveImage={props.saveImage}
            wide={studio.wide}
            onToggleWide={studio.toggleWide}
          />
        </div>
      </div>
    </div>
  );
}
