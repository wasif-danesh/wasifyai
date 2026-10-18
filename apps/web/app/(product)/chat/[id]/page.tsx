import { ChatHome } from "@/components/chat/ChatHome";
import { isUuid } from "@/lib/proxy";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

export const metadata: Metadata = { title: "Chat" };
type Props = { params: Promise<{ id: string }> };

export default async function Chat({ params }: Props) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  // keyed by the chat: moving from one chat to another starts the screen afresh
  return <ChatHome key={id} conversationId={id} />;
}
