"use client";

import { DeleteControls } from "@/components/create/shared";
import { Button } from "@/components/ui/button";
import { fullDate } from "@/lib/format";
import { actions, eyebrow, panel, player } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { SpeechSummary } from "@wasifyai/contracts";

/** A saved speech: the player, the words, a download and a two-step delete. */
export function SpeechView({ speech }: { speech: SpeechSummary }) {
  return (
    <article className={cn(panel, "@container")}>
      <figure className="m-0 grid">
        {/* biome-ignore lint/a11y/useMediaCaption: the text that is spoken is shown below */}
        <audio controls preload="metadata" src={speech.audio_url} className={player}>
          Your browser can't play this audio.
        </audio>
      </figure>
      <div className="grid gap-[0.9rem]">
        <span className={eyebrow}>
          {speech.language_name} · {speech.gender === "male" ? "Male" : "Female"} voice,{" "}
          {speech.voice} · {Math.round(speech.seconds)} seconds · {fullDate(speech.created_at)}
        </span>
        <p lang={speech.language}>{speech.text}</p>
        <div className={actions}>
          <Button asChild>
            <a href={`/api/products/wasifyai-tts/speeches/${speech.id}/download`} download>
              Download MP3
            </a>
          </Button>
          <DeleteControls url={`/api/products/wasifyai-tts/speeches/${speech.id}`} noun="speech" />
        </div>
      </div>
    </article>
  );
}
