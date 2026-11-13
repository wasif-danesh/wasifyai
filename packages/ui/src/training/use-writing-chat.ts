"use client";

import type { TrainingApi } from "@wasifyai/client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLanguageBases } from "./use-language-bases";

const words = (e: unknown, fallback: string) =>
  e instanceof Error && e.message ? e.message : fallback;

/**
 * Chat with a taught writing model (ADR-0074 decision 6): whether it is the one chat answers with, whether the chat
 * form of its base is on this computer (asked for once per base, with its size, before anything is fetched), and the
 * buttons to use it and to go back to the model that was chosen before.
 */
export function useWritingChat(api: TrainingApi, modelId: string, baseId: string, pollMs = 1500) {
  const [inChat, setInChat] = useState<string | null>(null);
  // where the chat engine is not this computer's (the web, for now) a taught model is not offered for chat
  const [canChat, setCanChat] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const lang = useLanguageBases(api, pollMs);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const read = useCallback(async () => {
    try {
      const s = await api.writingStatus();
      if (alive.current) {
        setInChat(s.in_chat);
        setCanChat(s.can_chat !== false);
      }
    } catch {
      /* chat is not offered where the engine has no language service */
    }
  }, [api]);

  useEffect(() => {
    void read();
  }, [read]);

  const base = lang.bases.find((b) => b.id === baseId) ?? null;
  const copy = base?.chat ?? null;

  const use = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await api.useWritingInChat(modelId);
      await read();
    } catch (e) {
      setError(words(e, "It could not be used in chat."));
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [api, modelId, read]);

  const stop = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await api.stopWritingInChat();
      await read();
    } catch (e) {
      setError(words(e, "It could not go back."));
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [api, read]);

  return {
    inChat,
    canChat,
    base,
    copy,
    busy,
    error: error ?? lang.error,
    use,
    stop,
    download: () => (copy ? lang.install(baseId, "chat", copy.bytes) : Promise.resolve()),
    cancel: () => lang.cancel(baseId, "chat"),
    mine: inChat === modelId,
  };
}
