import { ImageLibraryScreen } from "@/components/image/ImageScreens";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Your images" };

export default function ImageLibraryPage() {
  return <ImageLibraryScreen />;
}
