// SPDX-License-Identifier: AGPL-3.0-only
// The audio tools (ADR-0066, stage V4): split a recording into parts, make it sound like another voice,
// change some of its words. Each is a model chosen from a list; the result is kept in Your music.
import type { AudioSource } from "@wasifyai/client";
import { AudioToolWorkspace } from "@wasifyai/ui";
import { client, voiceApi } from "../api";
import { remembered } from "../remember";
import type { Route } from "../router";

type Tool = "separate" | "convert" | "edit";

const TITLE: Record<Tool, { title: string; lead: string }> = {
  separate: {
    title: "Split into parts",
    lead: "Take the singing, the drums and the rest out of a song, on this computer.",
  },
  convert: {
    title: "Change a voice",
    lead: "Make a recording sound like a voice you saved. Nothing leaves this computer.",
  },
  edit: {
    title: "Edit speech",
    lead: "Change some words in a recording and keep the voice.",
  },
};

const SOURCE_KEY = "wasifyai.tool.source";
const modelKey = (tool: Tool) => `wasifyai.tool.model.${tool}`;

/** The recording Your music sent to a tool ("track:<id>"); used once, then forgotten. */
export function sendToTool(source: AudioSource) {
  remembered.set(SOURCE_KEY, `${source.kind}:${source.id}`);
}

function takeSource(): AudioSource | null {
  const raw = remembered.get(SOURCE_KEY);
  if (raw) remembered.set(SOURCE_KEY, "");
  const m = /^(track|speech):([A-Za-z0-9-]{1,64})$/.exec(raw ?? "");
  return m ? { kind: m[1] as "track" | "speech", id: m[2] as string } : null;
}

export function ToolPage({ tool, go }: { tool: Tool; go: (r: Route) => void }) {
  const { title, lead } = TITLE[tool];
  return (
    <div className="grid gap-6 px-6 pt-10 pb-16">
      <header className="mx-auto w-full max-w-3xl">
        <h1 className="font-semibold text-2xl">{title}</h1>
        <p className="text-muted-foreground">{lead}</p>
      </header>
      <AudioToolWorkspace
        key={tool}
        api={voiceApi}
        runs={client}
        tool={tool}
        initialSource={takeSource()}
        initialModel={remembered.get(modelKey(tool))}
        onModelChosen={(id) => remembered.set(modelKey(tool), id)}
        onGetModel={() => go("models")}
        onOpenLibrary={() => go("tracks")}
        onOpenVoices={() => go("voices")}
      />
    </div>
  );
}
