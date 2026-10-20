"use client";

import { useAui } from "@assistant-ui/react";
import { type MutableRefObject, useEffect } from "react";
import { joinDictation } from "../dictation/use-dictation";

const MAX_CHARS = 4000;

/** Where `useComposerOptions` sends words from the microphone, set by `DictationBridge` once the runtime's box exists. */
export type DictationTarget = MutableRefObject<((text: string) => void) | null>;

/**
 * The options bar is built outside the runtime (it decides what the box offers), but the text of the box lives inside it. This renders
 * nothing; it hands the options bar a way to put dictated words after what the person has typed. They are never sent by themselves.
 */
export function DictationBridge({ target }: { target: DictationTarget }) {
  const aui = useAui();
  useEffect(() => {
    target.current = (text) => {
      const composer = aui.composer();
      composer.setText(joinDictation(composer.getState().text, text).slice(0, MAX_CHARS));
    };
    return () => {
      target.current = null;
    };
  }, [aui, target]);
  return null;
}
