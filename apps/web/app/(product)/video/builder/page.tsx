import { VideoBuilderScreen } from "@/components/videobuilder/VideoBuilderScreen";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Video Builder" };

export default function Page() {
  return <VideoBuilderScreen />;
}
