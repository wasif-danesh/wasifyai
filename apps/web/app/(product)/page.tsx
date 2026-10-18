import { ChatHome } from "@/components/chat/ChatHome";
import type { Metadata } from "next";

export const metadata: Metadata = { title: { absolute: "Wasify AI" } };

export default function Home() {
  return <ChatHome conversationId={null} />;
}
