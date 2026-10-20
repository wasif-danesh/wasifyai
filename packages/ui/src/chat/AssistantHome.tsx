"use client";

import {
  type AssistantApi,
  type ChatOptions,
  type DictationReadiness,
  type ImagesApi,
  type ReadAloudReadiness,
  type SpeechModelOffer,
  type VoiceApi,
  dictationReadiness,
  readAloudReadiness,
} from "@wasifyai/client";
import { Pencil, Trash2 } from "lucide-react";
import { type ReactNode, Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { ChatScreen, type ChatScreenProps } from "./ChatScreen";
import type { TrackLookup } from "./ToolCard";
import type { ComposerOptionsAvailable } from "./composer-options";
import { startRecording } from "./dictation/recorder";
import type { MicControl, MicSetup } from "./dictation/use-dictation";
import type { ReadAloudControl } from "./read-aloud/use-read-aloud";
import { conversationsChanged } from "./use-conversations";

export function greeting(hour: number): string {
  if (hour < 5) return "Good night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

// The new chat is a separate chunk: it brings assistant-ui and streamdown, which a person who has not turned it on never needs.
const ChatScreenNext = lazy(() =>
  import("./ChatScreenNext").then((m) => ({ default: m.ChatScreenNext })),
);

const EXAMPLES = [
  "Draw a lighthouse at sunrise",
  "What did I make last week?",
  "Explain how a transistor works",
];

export type AssistantHomeProps = {
  runs: ChatScreenProps["runs"];
  assistant: AssistantApi;
  images: ImagesApi;
  tracks?: TrackLookup;
  /** The saved conversation open; null is a new chat. */
  conversationId: string | null;
  /** A new chat got its first answer and so an id: the app gives it an address. */
  onAdopt: (id: string) => void;
  /** The open chat was deleted: the app goes to a new one. */
  onNewChat: () => void;
  /** Setup notices (no model chosen yet, and so on). */
  notices?: ReactNode;
  blockedReason?: string | null;
  onNeedModel?: () => void;
  onOpenCreation?: (kind: string, id: string) => void;
  /** Take the person to Settings, where the search service and its key are chosen (ADR-0083). */
  onOpenSettings?: () => void;
  /** Which options of the box the chat offers; by default what the engine says the model in use can do (ADR-0083). */
  composerOptions?: ChatScreenProps["composerOptions"];
  /**
   * The speech client, for the Mic (ADR-0083). Without it, or where the engine cannot write words down, the box has no Mic.
   * On the web the models are hosted and always ready; on the desktop a missing model is offered as a download.
   */
  voice?: VoiceApi;
  /** Fetch the speech model (desktop only: the web has no models to fetch). Reports how far it is, 0 to 1. */
  getSpeechModel?: (modelId: string, onProgress: (fraction: number) => void) => Promise<void>;
  /** Which chat screen to show: the one built on our own components (the default) or the new one on assistant-ui (Labs). */
  screen?: "classic" | "next";
};

/** The assistant is the home screen (ADR-0057): a greeting and "Ask anything", then the conversation, with
 * rename and delete once it is saved. Shared by the desktop window and the web app. */
export function AssistantHome({
  runs,
  assistant,
  images,
  tracks,
  conversationId,
  onAdopt,
  onNewChat,
  notices,
  blockedReason,
  onNeedModel,
  onOpenCreation,
  onOpenSettings,
  composerOptions,
  voice,
  getSpeechModel,
  screen = "classic",
}: AssistantHomeProps) {
  const [title, setTitle] = useState("");
  // what the box can offer with the model in use (a Thinking switch only for a model that can think, a Search switch
  // only when this engine can search at all)
  const [offered, setOffered] = useState<ChatOptions | null>(null);
  useEffect(() => {
    let gone = false;
    assistant
      .options()
      .then((o) => !gone && setOffered(o))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [assistant]);
  const allowSearch = useCallback(async () => {
    const st = await assistant.updateSearch({ consent: true });
    const chosen = st.providers.find((p) => p.id === st.provider);
    setOffered((o) =>
      o?.search
        ? {
            ...o,
            search: {
              ...o.search,
              consented: st.consented,
              ready: st.consented && !(chosen?.needs_key && !chosen.key_set),
            },
          }
        : o,
    );
  }, [assistant]);
  // whether the microphone can write words down here: a speech model is ready, or can be got, or the Mic is not shown
  const [speech, setSpeech] = useState<DictationReadiness | null>(null);
  // whether a reply can be read aloud here: a voice is ready, or can be got, or there is no Read aloud button
  const [voiceReady, setVoiceReady] = useState<ReadAloudReadiness | null>(null);
  const readSpeech = useCallback(async () => {
    if (!voice) return;
    try {
      const [models, runtime] = await Promise.all([voice.models("transcribe"), voice.runtime()]);
      setSpeech(dictationReadiness(models, runtime));
    } catch {
      setSpeech({ state: "unavailable" });
    }
    try {
      const [models, runtime] = await Promise.all([voice.models("speak"), voice.runtime()]);
      setVoiceReady(readAloudReadiness(models, runtime));
    } catch {
      setVoiceReady({ state: "unavailable" });
    }
  }, [voice]);
  useEffect(() => {
    void readSpeech();
  }, [readSpeech]);
  // getting a speech model (and the runtime that runs it, when that is missing), after the click that followed the card
  const setupFor = useCallback(
    (
      model: SpeechModelOffer,
      runtimeBytes: number,
      fetchModel: NonNullable<typeof getSpeechModel>,
    ): MicSetup & { languages: string[] } => ({
      title: model.title,
      licence: model.licence,
      from: model.from,
      languages: model.languages,
      bytes: model.bytes + runtimeBytes,
      run: async (onProgress) => {
        if (!voice) return;
        if (runtimeBytes > 0) {
          onProgress(null);
          await voice.installRuntime(runtimeBytes);
          for (;;) {
            const rt = await voice.runtime();
            if (rt.install.state === "failed") throw new Error(rt.install.message);
            if (rt.installed) break;
            await new Promise((r) => setTimeout(r, 500));
          }
        }
        if (model.bytes > 0) await fetchModel(model.id, onProgress);
        await readSpeech();
      },
    }),
    [voice, readSpeech],
  );
  const mic = useMemo<MicControl | undefined>(() => {
    if (!voice || !speech || speech.state === "unavailable") return undefined;
    const base: MicControl = { record: startRecording, transcribe: (wav) => voice.dictate(wav) };
    if (speech.state === "ready") return base;
    if (!getSpeechModel) return undefined; // nothing here can fetch a model (the web): no button
    return { ...base, setup: setupFor(speech.model, speech.runtimeBytes, getSpeechModel) };
  }, [voice, speech, getSpeechModel, setupFor]);
  const readAloud = useMemo<ReadAloudControl | undefined>(() => {
    if (!voice || !voiceReady || voiceReady.state === "unavailable") return undefined;
    const base: ReadAloudControl = {
      speak: (text, part, signal) => voice.readAloud(text, part, signal),
    };
    if (voiceReady.state === "ready") return base;
    if (!getSpeechModel) return undefined; // nothing here can fetch a model (the web): no button
    return { ...base, setup: setupFor(voiceReady.model, voiceReady.runtimeBytes, getSpeechModel) };
  }, [voice, voiceReady, getSpeechModel, setupFor]);
  const engineOptions = useMemo<ComposerOptionsAvailable>(() => {
    const s = offered?.search;
    const a = offered?.attach;
    return {
      mic,
      readAloud,
      // files: only where the engine can keep them (a model that cannot read pictures still takes documents)
      attach: a?.available
        ? {
            images: a.images,
            documents: a.documents,
            imagesNote: a.images_note,
            upload: (file, name) => assistant.attach(file, name),
            discard: (id) => assistant.unattach(id),
          }
        : undefined,
      thinking: offered?.thinking,
      search: s?.available
        ? {
            available: true,
            consented: s.consented,
            ready: s.ready,
            providerTitle: s.provider_title,
            consentText: s.consent_text,
            needsKey: s.needs_key,
            onAllow: allowSearch,
            onOpenSettings,
          }
        : undefined,
    };
  }, [offered, allowSearch, onOpenSettings, mic, readAloud, assistant]);
  // the hour is read in the browser, so a page rendered on a server says the same as the person's clock
  const [hour, setHour] = useState<number | null>(null);
  useEffect(() => setHour(new Date().getHours()), []);

  useEffect(() => {
    if (!conversationId) {
      setTitle("");
      return;
    }
    let gone = false;
    assistant
      .list(100)
      .then((l) => !gone && setTitle(l.find((c) => c.id === conversationId)?.title ?? ""))
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [conversationId, assistant]);

  async function rename() {
    if (!conversationId) return;
    const next = window.prompt("Name this chat", title)?.trim();
    if (!next) return;
    try {
      const c = await assistant.rename(conversationId, next);
      setTitle(c.title);
      conversationsChanged();
    } catch {
      // the name stays as it was
    }
  }

  async function remove() {
    if (!conversationId) return;
    if (!window.confirm("Delete this chat? What it made stays in your library.")) return;
    try {
      await assistant.remove(conversationId);
      conversationsChanged();
      onNewChat();
    } catch {
      // still there: nothing to do
    }
  }

  const hero = (
    <h1 className="flex items-center gap-4 font-medium text-4xl tracking-tight">
      <span
        aria-hidden="true"
        className="grid size-14 place-items-center rounded-full bg-primary font-bold text-2xl text-primary-foreground"
      >
        w
      </span>
      {hour === null ? "Hello" : greeting(hour)}
    </h1>
  );

  const shared: ChatScreenProps = {
    runs,
    assistant,
    images,
    tracks,
    conversationId,
    onConversation: (id) => {
      conversationsChanged();
      if (!conversationId) onAdopt(id); // a new chat now has an address, and stays as it is
    },
    hero,
    examples: conversationId ? [] : EXAMPLES,
    notices,
    blockedReason,
    onNeedModel,
    onOpenCreation,
    composerOptions: composerOptions ?? engineOptions,
    title: conversationId ? title || "Chat" : undefined,
    actions: conversationId ? (
      <>
        <button
          type="button"
          aria-label="Rename this chat"
          className="rounded-md p-2 text-muted-foreground hover:bg-accent"
          onClick={() => void rename()}
        >
          <Pencil className="size-4" />
        </button>
        <button
          type="button"
          aria-label="Delete this chat"
          className="rounded-md p-2 text-muted-foreground hover:bg-accent"
          onClick={() => void remove()}
        >
          <Trash2 className="size-4" />
        </button>
      </>
    ) : undefined,
  };

  return screen === "next" ? (
    <Suspense fallback={null}>
      <ChatScreenNext {...shared} />
    </Suspense>
  ) : (
    <ChatScreen {...shared} />
  );
}
