"use client";

import type { AudioSource, ParsedEvent, VoiceApi } from "@wasifyai/client";
import { type ReactNode, useRef, useState } from "react";
import { TopBarSlot } from "../window-bar";
import { AudioToolWorkspace } from "./AudioToolWorkspace";
import { AudiobookWorkspace } from "./AudiobookWorkspace";
import { DubbingWorkspace } from "./DubbingWorkspace";
import { LipSyncWorkspace } from "./LipSyncWorkspace";
import { LyricsWriter } from "./LyricsWriter";
import { MusicWorkspace } from "./MusicWorkspace";
import { SpeakWorkspace } from "./SpeakWorkspace";
import { TrackList } from "./TrackList";
import { TranscribeWorkspace } from "./TranscribeWorkspace";
import { VoicesWorkspace } from "./VoicesWorkspace";

// The voice screens of the desktop window and of the web app, each with its heading, the hand-offs
// between them (lyrics to Create music, a track to a tool, a voice to Text to speech) and the model last
// chosen. The two apps differ in what they pass: the engine they talk to, where small things are
// remembered, how a screen is opened, and whether the models run on this computer (`device`) or in a
// service (`service`), which changes the sentences that make promises about where things go.

/** Where a small thing is kept between screens and visits: a model chosen last time, a hand-off. */
export type Remembered = {
  get(key: string): string | null;
  set(key: string, value: string): void;
};

/** A screen a voice page can open. */
export type VoiceTarget =
  | "speak"
  | "music"
  | "tracks"
  | "separate"
  | "convert"
  | "speechedit"
  | "voices"
  | "models";

export type Runs = {
  startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
};

export type VoicePageProps = {
  api: VoiceApi;
  runs: Runs;
  remembered: Remembered;
  go: (to: VoiceTarget) => void;
  place: "device" | "service";
};

function Frame({ title, lead, children }: { title: string; lead: ReactNode; children: ReactNode }) {
  return (
    <TopBarSlot>
      <div className="grid gap-6 px-6 pt-10 pb-16">
        <header className="mx-auto w-full max-w-3xl">
          <h1 className="font-semibold text-2xl">{title}</h1>
          <p className="text-muted-foreground">{lead}</p>
        </header>
        {children}
      </div>
    </TopBarSlot>
  );
}

/** A screen on the one make screen (ADR-0093): the frame fills the window under the top bar. */
function MakeFrame({ children }: { children: ReactNode }) {
  return (
    <TopBarSlot>
      <div data-workspace className="flex h-[calc(100dvh-3rem)] min-h-[32rem] flex-col">
        {children}
      </div>
    </TopBarSlot>
  );
}

const device = (p: VoicePageProps, onDevice: string, onService: string) =>
  p.place === "device" ? onDevice : onService;

/** The model screens offer to fetch a missing model: only where a person can (the desktop's Models). */
const getModel = (p: VoicePageProps) => (p.place === "device" ? () => p.go("models") : undefined);

// ---- hand-offs: used once, then forgotten --------------------------------------------------------

const USE_VOICE = "wasifyai.voice.use";
const LYRICS = "wasifyai.music.lyrics";
const OPEN = "wasifyai.music.open";
const SOURCE = "wasifyai.tool.source";

function take(r: Remembered, key: string): string | null {
  const v = r.get(key);
  if (v) r.set(key, "");
  return v || null;
}

/** Send a recording from Your music to a tool. */
export function sendToTool(r: Remembered, source: AudioSource) {
  r.set(SOURCE, `${source.kind}:${source.id}`);
}

/** Open Create music with a track: change it (`edit`), make it again with its seed (`again`) or a new one (`take`). */
export function openInMusic(r: Remembered, kind: "edit" | "again" | "take", trackId: string) {
  r.set(OPEN, `${kind}:${trackId}`);
}

function takeSource(r: Remembered): AudioSource | null {
  const m = /^(track|speech):([A-Za-z0-9-]{1,64})$/.exec(take(r, SOURCE) ?? "");
  return m ? { kind: m[1] as "track" | "speech", id: m[2] as string } : null;
}

function takeAction(r: Remembered) {
  const m = /^(edit|again|take):([A-Za-z0-9]{1,64})$/.exec(take(r, OPEN) ?? "");
  return m ? { kind: m[1] as "edit" | "again" | "take", trackId: m[2] as string } : null;
}

// ---- the pages -----------------------------------------------------------------------------------

export function SpeakPage(p: VoicePageProps) {
  // read once: a render that runs twice must not lose the voice that was sent here
  const [voice] = useState(() => take(p.remembered, USE_VOICE));
  const key = "wasifyai.voice.model.speak";
  return (
    <MakeFrame>
      <SpeakWorkspace
        api={p.api}
        runs={p.runs}
        lead={device(
          p,
          "Type something and hear it. It is made on this computer; nothing is sent away.",
          "Type something and hear it. The speech is kept in your account. A model marked Hosted sends the text to its provider.",
        )}
        onGetModel={getModel(p)}
        initialModel={p.remembered.get(key)}
        onModelChosen={(id) => p.remembered.set(key, id)}
        initialSavedVoice={voice}
        onTool={(speech, tool) => {
          sendToTool(p.remembered, { kind: "speech", id: speech.id });
          p.go(tool === "convert" ? "convert" : "speechedit");
        }}
      />
    </MakeFrame>
  );
}

export function TranscribePage(p: VoicePageProps) {
  const key = "wasifyai.voice.model.transcribe";
  return (
    <MakeFrame>
      <TranscribeWorkspace
        api={p.api}
        lead={device(
          p,
          "Turn a recording into text with times. It is read on this computer; nothing is sent away.",
          "Turn a recording into text with times. The text is kept in your account; the recording is not. A model marked Hosted sends the recording to its provider.",
        )}
        onGetModel={getModel(p)}
        initialModel={p.remembered.get(key)}
        onModelChosen={(id) => p.remembered.set(key, id)}
      />
    </MakeFrame>
  );
}

export function VoicesPage(p: VoicePageProps) {
  return (
    <Frame
      title="Voices"
      lead={device(
        p,
        "Describe a voice or copy one from a short recording, then use it in Text to speech. Voices stay on this computer.",
        "Describe a voice or copy one from a short recording, then use it in Text to speech. Voices are kept in your account, and a copied voice needs the speaker's permission.",
      )}
    >
      <VoicesWorkspace
        api={p.api}
        runs={p.runs}
        onUseVoice={(id) => {
          p.remembered.set(USE_VOICE, id);
          p.go("speak");
        }}
      />
    </Frame>
  );
}

export function MusicPage(p: VoicePageProps) {
  const [lyrics] = useState(() => take(p.remembered, LYRICS));
  const [action] = useState(() => takeAction(p.remembered));
  const key = "wasifyai.music.model";
  return (
    <MakeFrame>
      <MusicWorkspace
        api={p.api}
        runs={p.runs}
        lead={device(
          p,
          "Songs, instrumentals and sound effects, made on this computer.",
          "Songs, instrumentals and sound effects.",
        )}
        onGetModel={getModel(p)}
        initialModel={p.remembered.get(key)}
        onModelChosen={(id) => p.remembered.set(key, id)}
        initialLyrics={lyrics}
        initialAction={action}
        onOpenLibrary={() => p.go("tracks")}
        onSplit={(t) => {
          sendToTool(p.remembered, { kind: "track", id: t.id });
          p.go("separate");
        }}
      />
    </MakeFrame>
  );
}

export function TracksPage(p: VoicePageProps) {
  const [added, setAdded] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const add = async (file: File) => {
    setProblem(null);
    try {
      await p.api.importTrack(file);
      setAdded((n) => n + 1);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "That recording could not be added.");
    }
  };
  const open = (kind: "edit" | "again" | "take", id: string) => {
    openInMusic(p.remembered, kind, id);
    p.go("music");
  };
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto flex w-full max-w-3xl flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-semibold text-2xl">Your music</h1>
        <div className="flex items-baseline gap-4">
          <input
            ref={picker}
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.caf,.aiff"
            className="sr-only"
            aria-label="Add a recording from this computer"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void add(f);
            }}
          />
          <button
            type="button"
            className="text-sm underline underline-offset-4"
            onClick={() => picker.current?.click()}
          >
            Add a recording
          </button>
          <button
            type="button"
            className="text-sm underline underline-offset-4"
            onClick={() => p.go("music")}
          >
            Make something new
          </button>
        </div>
      </header>
      {problem ? (
        <p role="alert" className="mx-auto w-full max-w-3xl text-destructive text-sm">
          {problem}
        </p>
      ) : null}
      <div className="mx-auto w-full max-w-3xl">
        <TrackList
          api={p.api}
          heading="Everything you made"
          searchable
          onAgain={(t) => open("again", t.id)}
          onTake={(t) => open("take", t.id)}
          onEdit={(t) => open("edit", t.id)}
          refreshKey={added}
          onTool={(t, tool) => {
            sendToTool(p.remembered, { kind: "track", id: t.id });
            p.go(tool === "separate" ? "separate" : tool === "convert" ? "convert" : "speechedit");
          }}
        />
      </div>
    </div>
  );
}

export function LyricsPage(p: VoicePageProps) {
  return (
    <Frame
      title="Lyrics"
      lead={device(
        p,
        "The chat model you chose writes the words; you can change them, then take them to Create music. Nothing leaves this computer.",
        "A chat model writes the words; you can change them, then take them to Create music.",
      )}
    >
      <div className="mx-auto w-full max-w-3xl">
        <LyricsWriter
          runs={p.runs}
          duration={60}
          useLabel="Use in Create music"
          onUse={(words) => {
            p.remembered.set(LYRICS, words);
            p.go("music");
          }}
        />
      </div>
    </Frame>
  );
}

export type AudioToolName = "separate" | "convert" | "edit";

const TOOL_TEXT: Record<AudioToolName, { title: string; device: string; service: string }> = {
  separate: {
    title: "Split into parts",
    device: "Take the singing, the drums and the rest out of a song, on this computer.",
    service: "Take the singing, the drums and the rest out of a song.",
  },
  convert: {
    title: "Change a voice",
    device: "Make a recording sound like a voice you saved. Nothing leaves this computer.",
    service: "Make a recording sound like a voice you saved.",
  },
  edit: {
    title: "Edit speech",
    device: "Change some words in a recording and keep the voice.",
    service: "Change some words in a recording and keep the voice.",
  },
};

export function ToolPage({ tool, ...p }: VoicePageProps & { tool: AudioToolName }) {
  const text = TOOL_TEXT[tool];
  const key = `wasifyai.tool.model.${tool}`;
  const [source] = useState(() => takeSource(p.remembered));
  return (
    <MakeFrame>
      <AudioToolWorkspace
        key={tool}
        api={p.api}
        runs={p.runs}
        tool={tool}
        title={text.title}
        lead={device(p, text.device, text.service)}
        initialSource={source}
        initialModel={p.remembered.get(key)}
        onModelChosen={(id) => p.remembered.set(key, id)}
        onGetModel={getModel(p)}
        onOpenLibrary={() => p.go("tracks")}
        onOpenVoices={() => p.go("voices")}
      />
    </MakeFrame>
  );
}

export function DubPage(p: VoicePageProps) {
  const key = "wasifyai.dub.model";
  return (
    <MakeFrame>
      <DubbingWorkspace
        api={p.api}
        runs={p.runs}
        lead="Hear a recording in another language, in the speaker's voice or one you choose. The result is kept in Your music."
        onGetModel={getModel(p)}
        initialModel={p.remembered.get(key)}
        onModelChosen={(id) => p.remembered.set(key, id)}
        onOpenLibrary={() => p.go("tracks")}
      />
    </MakeFrame>
  );
}

export function AudiobookPage(p: VoicePageProps) {
  const key = "wasifyai.audiobook.model";
  return (
    <MakeFrame>
      <AudiobookWorkspace
        api={p.api}
        runs={p.runs}
        lead={device(
          p,
          "Read a long text aloud, chapter by chapter, in a voice you choose. It runs on this computer.",
          "Read a long text aloud, chapter by chapter, in a voice you choose. Every chapter is kept in Your music as it is done.",
        )}
        onGetModel={getModel(p)}
        initialModel={p.remembered.get(key)}
        onModelChosen={(id) => p.remembered.set(key, id)}
        onOpenLibrary={() => p.go("tracks")}
      />
    </MakeFrame>
  );
}

export function LipSyncPage(p: VoicePageProps) {
  const key = "wasifyai.lipsync.model";
  return (
    <MakeFrame>
      <LipSyncWorkspace
        api={p.api}
        runs={p.runs}
        lead={device(
          p,
          "Make the face in a picture say your words or a recording. It runs on this computer, and every video is marked as AI-generated.",
          "Make the face in a picture say your words or a recording. Every video is marked as AI-generated.",
        )}
        onGetModel={getModel(p)}
        initialModel={p.remembered.get(key)}
        onModelChosen={(id) => p.remembered.set(key, id)}
      />
    </MakeFrame>
  );
}
