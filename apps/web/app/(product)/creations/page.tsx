import { Notice } from "@/components/Notice";
import { CreationsList } from "@/components/creations/CreationsList";
import { PageHero } from "@/components/ui/page-hero";
import { apiGet } from "@/lib/api";
import { PRODUCT } from "@/lib/run-client";
import type {
  ImagePage,
  LipSyncPage,
  SongPage,
  SpeechPage,
  TranscriptPage,
  VideoPage,
} from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "My creations" };
export const dynamic = "force-dynamic";

const FILTERS = ["songs", "images", "videos", "speeches", "transcripts", "lipsyncs"] as const;

export default async function Creations({
  searchParams,
}: {
  searchParams: Promise<{ show?: string }>;
}) {
  const { show } = await searchParams;
  const initialFilter = FILTERS.find((f) => f === show) ?? "all";
  const [
    songsResult,
    imagesResult,
    videosResult,
    speechesResult,
    transcriptsResult,
    lipsyncsResult,
  ] = await Promise.allSettled([
    apiGet<SongPage>(`/products/${PRODUCT}/songs?limit=12`),
    apiGet<ImagePage>("/products/wasifyai-image/images?limit=12"),
    apiGet<VideoPage>("/products/wasifyai-video/videos?limit=12"),
    apiGet<SpeechPage>("/products/wasifyai-tts/speeches?limit=12"),
    apiGet<TranscriptPage>("/products/wasifyai-stt/transcripts?limit=12"),
    apiGet<LipSyncPage>("/products/wasifyai-lipsync/lipsyncs?limit=12"),
  ]);
  const songs = songsResult.status === "fulfilled" ? songsResult.value : null;
  const images = imagesResult.status === "fulfilled" ? imagesResult.value : null;
  const videos = videosResult.status === "fulfilled" ? videosResult.value : null;
  const speeches = speechesResult.status === "fulfilled" ? speechesResult.value : null;
  const transcripts = transcriptsResult.status === "fulfilled" ? transcriptsResult.value : null;
  const lipsyncs = lipsyncsResult.status === "fulfilled" ? lipsyncsResult.value : null;

  return (
    <>
      <PageHero
        eyebrow="YOUR LIBRARY"
        title="My creations"
        className="pt-[clamp(1.5rem,4vw,3rem)] pb-4 [&_p]:max-w-[34rem]"
      >
        Your songs, images, videos, speech, transcripts and lip syncs, all together. Pick up where
        inspiration left off.
      </PageHero>
      {songs || images || videos || speeches || transcripts || lipsyncs ? (
        <>
          {songsResult.status === "rejected" ? (
            <Notice tone="error" title="Couldn't load your songs">
              Your other creations are still available below.
            </Notice>
          ) : null}
          {imagesResult.status === "rejected" ? (
            <Notice tone="error" title="Couldn't load your images">
              Your other creations are still available below.
            </Notice>
          ) : null}
          {videosResult.status === "rejected" ? (
            <Notice tone="error" title="Couldn't load your videos">
              Your other creations are still available below.
            </Notice>
          ) : null}
          {speechesResult.status === "rejected" ? (
            <Notice tone="error" title="Couldn't load your speech">
              Your other creations are still available below.
            </Notice>
          ) : null}
          {transcriptsResult.status === "rejected" ? (
            <Notice tone="error" title="Couldn't load your transcripts">
              Your other creations are still available below.
            </Notice>
          ) : null}
          {lipsyncsResult.status === "rejected" ? (
            <Notice tone="error" title="Couldn't load your lip syncs">
              Your other creations are still available below.
            </Notice>
          ) : null}
          <CreationsList
            songs={songs}
            images={images}
            videos={videos}
            speeches={speeches}
            transcripts={transcripts}
            lipsyncs={lipsyncs}
            initialFilter={initialFilter}
          />
        </>
      ) : (
        <Notice tone="error" title="Couldn't load your creations">
          The service isn't answering right now. Try again in a moment.
        </Notice>
      )}
    </>
  );
}
