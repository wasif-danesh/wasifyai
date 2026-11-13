import { VideoScreen } from "@/components/video/VideoScreens";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Extend a video" };

export default function ExtendPage() {
  return <VideoScreen mode="extend" />;
}
