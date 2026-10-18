import { VideoScreen } from "@/components/video/VideoScreens";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Animate a picture" };

export default function AnimatePage() {
  return <VideoScreen mode="image" />;
}
