"use client";

import { useEffect, useRef, useState } from "react";
import { firstFile, hasFiles } from "../pictures";

/**
 * Drag and drop and paste for a picture form (ADR-0039). While the form is on screen a picture dropped
 * anywhere on the page, or pasted anywhere, is handed to `onFile`, and the browser never navigates to a
 * dropped file. A text paste is left alone, so the prompt box works as usual. Returns whether a file is
 * being dragged over the page, for the highlight.
 */
export function usePictureEvents(onFile: (file: File) => void, enabled = true) {
  const [dragging, setDragging] = useState(false);
  const handler = useRef(onFile);
  handler.current = onFile;

  useEffect(() => {
    if (!enabled) return;
    let depth = 0;

    const over = (e: DragEvent) => {
      if (!hasFiles(e.dataTransfer)) return;
      e.preventDefault(); // allows the drop, and stops the browser opening the file
    };
    const enter = (e: DragEvent) => {
      if (!hasFiles(e.dataTransfer)) return;
      depth += 1;
      setDragging(true);
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e.dataTransfer)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e.dataTransfer)) return;
      e.preventDefault();
      depth = 0;
      setDragging(false);
      const file = firstFile(e.dataTransfer);
      if (file) handler.current(file);
    };
    const paste = (e: ClipboardEvent) => {
      const data = e.clipboardData;
      // a spreadsheet copy carries a picture and text: the text wins, as the user expects
      if (!data || Array.from(data.types).includes("text/plain")) return;
      const file = firstFile(data);
      if (!file) return;
      e.preventDefault();
      handler.current(file);
    };

    window.addEventListener("dragover", over);
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    document.addEventListener("paste", paste);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
      document.removeEventListener("paste", paste);
      setDragging(false);
    };
  }, [enabled]);

  return { dragging };
}
