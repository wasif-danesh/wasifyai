import { VoiceScreen } from "@/components/voice/VoiceScreen";
import { VOICE_SCREENS, isVoiceScreen } from "@/lib/voice-screens";
import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";

type Props = { params: Promise<{ screen: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { screen } = await params;
  return { title: isVoiceScreen(screen) ? VOICE_SCREENS[screen].title : "Voice" };
}

export default async function VoicePage({ params }: Props) {
  const { screen } = await params;
  if (screen === "tracks") redirect("/creations?show=songs"); // "Your music" is the Library now (ADR-0093, U8)
  if (!isVoiceScreen(screen)) notFound();
  return <VoiceScreen screen={screen} />;
}
