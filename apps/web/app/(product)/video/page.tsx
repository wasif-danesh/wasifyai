import { VideoScreen } from "@/components/video/VideoScreens";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Video" };

export default function VideoPage() {
  return <VideoScreen mode="text" />;
}
