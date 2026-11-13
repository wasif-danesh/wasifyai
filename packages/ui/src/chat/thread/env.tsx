"use client";

import type { ImagesApi } from "@wasifyai/client";
import { type ReactNode, createContext, useContext } from "react";
import type { TrackLookup } from "../ToolCard";

/** What the parts of a message need from the app: the library to read a picture from, the music lookup, a way to open a
 * creation, and the origins a picture inside an answer may load from. The screen provides it once. */
export type ThreadEnv = {
  images: ImagesApi;
  tracks?: TrackLookup;
  onOpenCreation?: (kind: string, id: string) => void;
  /** Take the person to Settings (a search service that fails: add a key there) */
  onOpenSettings?: () => void;
  /** origins a markdown picture may load from (none by default) */
  imageOrigins?: string[];
  /** Thinking is on for this chat: a pending answer says it takes longer */
  thinkingOn?: boolean;
  /** The person answered a card that waits for them (ADR-0071): yes or no, with the fields as they edited them */
  onDecide?: (approved: boolean, params?: Record<string, unknown>) => void;
  /** Open a screen of the app by its menu item id (the assistant's open_screen button, ADR-0071) */
  onOpenScreen?: (screenId: string) => void;
  /** The person ticked "Don't ask again in this chat" on a card: the chat stops asking before it makes things */
  onAutoRun?: () => void;
  /** A change the assistant made in a screen it is docked in: can it still be undone from its card, and how */
  undoOfTool?: (toolId: string) => { undone: boolean; undo: () => void } | null;
  /** The notebook chat (CU4) is a plain back-and-forth: no edit, no "answer again", no versions. */
  linear?: boolean;
  /** What a waiting answer says (default: "Thinking…"). */
  pending?: string;
  /** A line above an answer (what was searched). */
  lead?: (messageId: string) => ReactNode;
  /** More buttons beside Copy (Save as note). */
  extras?: (messageId: string) => ReactNode;
  /** `[n]` source labels in an answer, drawn as pills; without it a label stays text. */
  renderLabel?: (messageId: string, n: number) => ReactNode;
};

const Env = createContext<ThreadEnv | null>(null);

export function ThreadEnvProvider({ value, children }: { value: ThreadEnv; children: ReactNode }) {
  return <Env.Provider value={value}>{children}</Env.Provider>;
}

export function useThreadEnv(): ThreadEnv {
  const env = useContext(Env);
  if (!env) throw new Error("A message part was rendered outside ThreadEnvProvider");
  return env;
}
