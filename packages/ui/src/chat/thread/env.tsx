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
  /** origins a markdown picture may load from (none by default) */
  imageOrigins?: string[];
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
