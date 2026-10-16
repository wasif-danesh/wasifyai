"use client";

import { type LyricsRequest, type ParsedEvent, makeLyrics } from "@wasifyai/client";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/button";
import { Label } from "../components/label";
import { Spinner } from "../components/spinner";
import { Textarea } from "../components/textarea";

export type LyricsWriterProps = {
  runs: {
    startRun(p: string, input: object, s: AbortSignal, on: (e: ParsedEvent) => void): Promise<void>;
  };
  /** what the music is like and how long it is: both shape the words */
  style?: string;
  duration?: number;
  /** the words are ready: put them where they are used */
  onUse?: (lyrics: string) => void;
  useLabel?: string;
  /** the words so far, for a screen that wants to keep them */
  initial?: string;
};

/** Lyrics written by the chat model the person chose. The words stream in, can be changed by hand, and
 * are copied or sent to the music form. */
export function LyricsWriter({
  runs,
  style,
  duration,
  onUse,
  useLabel = "Use these lyrics",
  initial = "",
}: LyricsWriterProps) {
  const [idea, setIdea] = useState("");
  const [language, setLanguage] = useState("English");
  const [words, setWords] = useState(initial);
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  async function write() {
    if (working || idea.trim().length < 3) return;
    setProblem(null);
    setWorking(true);
    setCopied(false);
    abort.current = new AbortController();
    const request: LyricsRequest = {
      idea,
      language,
      ...(style ? { style } : {}),
      ...(duration !== undefined ? { duration } : {}),
    };
    try {
      const r = await makeLyrics(runs, request, abort.current.signal, setWords);
      if (r.ok) setWords(r.lyrics);
      else {
        setProblem(r.message);
        setWords(initial);
      }
    } catch (e) {
      if (!abort.current.signal.aborted) {
        setProblem(e instanceof Error ? e.message : "The words could not be written.");
      }
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="grid gap-3">
      <div className="grid gap-2">
        <Label htmlFor="lyrics-idea">What is the song about?</Label>
        <input
          id="lyrics-idea"
          className="h-10 rounded-md border border-input bg-transparent px-3 text-sm"
          value={idea}
          maxLength={500}
          disabled={working}
          placeholder="A summer day by the sea with an old friend"
          onChange={(e) => setIdea(e.target.value)}
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="lyrics-language">Language</Label>
        <input
          id="lyrics-language"
          className="h-9 w-48 rounded-md border border-input bg-transparent px-2 text-sm"
          value={language}
          maxLength={40}
          disabled={working}
          onChange={(e) => setLanguage(e.target.value)}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => void write()} disabled={working || idea.trim().length < 3}>
          {working ? "Writing…" : words ? "Write again" : "Write the lyrics"}
        </Button>
        {working ? (
          <>
            <Spinner />
            <Button variant="ghost" onClick={() => abort.current?.abort()}>
              Stop
            </Button>
          </>
        ) : null}
      </div>
      {problem ? (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      ) : null}
      {words ? (
        <div className="grid gap-2">
          <Label htmlFor="lyrics-words">The lyrics (you can change them)</Label>
          <Textarea
            id="lyrics-words"
            rows={12}
            value={words}
            maxLength={5000}
            disabled={working}
            onChange={(e) => setWords(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            {onUse ? (
              <Button variant="outline" onClick={() => onUse(words)} disabled={working}>
                {useLabel}
              </Button>
            ) : null}
            <Button
              variant="ghost"
              disabled={working}
              onClick={() => {
                void navigator.clipboard?.writeText(words);
                setCopied(true);
              }}
            >
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
