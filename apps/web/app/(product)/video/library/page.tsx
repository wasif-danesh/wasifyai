import { VideoLibraryScreen } from "@/components/video/VideoScreens";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Your videos" };

export default function VideoLibraryPage() {
  return <VideoLibraryScreen />;
}
