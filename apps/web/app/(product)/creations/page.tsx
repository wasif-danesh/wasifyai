import { Notice } from "@/components/Notice";
import { CreationsList } from "@/components/creations/CreationsList";
import { PageHero } from "@/components/ui/page-hero";
import { apiGet } from "@/lib/api";
import {
  clipFromVoice,
  speechFromVoice,
  trackFromVoice,
  transcriptFromVoice,
  voiceOn,
} from "@/lib/voice-cards";
import type { ImagePage, VideoPage } from "@wasifyai/contracts";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "My creations" };
export const dynamic = "force-dynamic";

const FILTERS = ["songs", "images", "videos", "speeches", "transcripts", "lipsyncs"] as const;

type Items<T> = { items: T[] };
const voiceList = <T,>(kind: string): Promise<Items<T>> =>
  voiceOn()
    ? apiGet<Items<T>>(`/products/wasifyai-voice/${kind}?limit=100`)
    : Promise.resolve({ items: [] });

export default async function Creations({
  searchParams,
}: {
  searchParams: Promise<{ show?: string }>;
}) {
  const { show } = await searchParams;
  const initialFilter = FILTERS.find((f) => f === show) ?? "all";
  const [imagesResult, videosResult, tracksResult, speechesResult, transcriptsResult, clipsResult] =
    await Promise.allSettled([
      apiGet<ImagePage>("/products/wasifyai-image/images?limit=12"),
      apiGet<VideoPage>("/products/wasifyai-video/videos?limit=12"),
      voiceList<Parameters<typeof trackFromVoice>[0]>("tracks"),
      voiceList<Parameters<typeof speechFromVoice>[0]>("speeches"),
      voiceList<Parameters<typeof transcriptFromVoice>[0]>("transcripts"),
      voiceList<Parameters<typeof clipFromVoice>[0]>("clips"),
    ]);
  const ok = <T,>(r: PromiseSettledResult<T>) => (r.status === "fulfilled" ? r.value : null);
  const images = ok(imagesResult);
  const videos = ok(videosResult);
  const tracks = ok(tracksResult)?.items.map(trackFromVoice) ?? [];
  const speeches = ok(speechesResult)?.items.map(speechFromVoice) ?? [];
  const transcripts = ok(transcriptsResult)?.items.map(transcriptFromVoice) ?? [];
  const clips = ok(clipsResult)?.items.map(clipFromVoice) ?? [];
  const voiceFailed = [tracksResult, speechesResult, transcriptsResult, clipsResult].some(
    (r) => r.status === "rejected",
  );

  return (
    <>
      <PageHero
        eyebrow="YOUR LIBRARY"
        title="My creations"
        className="pt-[clamp(1.5rem,4vw,3rem)] pb-4 [&_p]:max-w-[34rem]"
      >
        Your music, images, videos, speech, transcripts and lip syncs, all together. Pick up where
        inspiration left off.
      </PageHero>
      {images ||
      videos ||
      tracks.length ||
      speeches.length ||
      transcripts.length ||
      clips.length ? (
        <>
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
          {voiceFailed ? (
            <Notice tone="error" title="Couldn't load your music, speech or lip syncs">
              Your other creations are still available below.
            </Notice>
          ) : null}
          <CreationsList
            songs={tracks}
            images={images}
            videos={videos}
            speeches={speeches}
            transcripts={transcripts}
            lipsyncs={clips}
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
