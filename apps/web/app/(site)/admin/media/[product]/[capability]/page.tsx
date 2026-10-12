import { Notice } from "@/components/Notice";
import { MediaForm } from "@/components/admin/MediaForm";
import { TextLink } from "@/components/ui/text-link";
import { apiGet } from "@/lib/api";
import { muted, pager } from "@/lib/styles";
import type { MediaList } from "@wasifyai/contracts";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ product: string; capability: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { product, capability } = await params;
  return { title: `${product} ${capability}` };
}

export default async function EditMedia({ params }: Params) {
  const { product, capability } = await params;
  let list: MediaList | null = null;
  try {
    list = await apiGet<MediaList>("/admin/media");
  } catch {
    // shown below
  }
  if (!list) {
    return (
      <Notice tone="error" title="Couldn't load the media settings">
        The service isn't answering right now.
      </Notice>
    );
  }
  const item = list.items.find((i) => i.product_id === product && i.capability === capability);
  if (!item) notFound();
  const current = list.backends.find((b) => b.id === item.backend)?.label ?? item.backend;
  return (
    <>
      <p className={pager}>
        <TextLink href="/admin/media">← Media</TextLink>
      </p>
      <header className="grid gap-[0.9rem]">
        <h2 className="text-step-1 font-semibold">
          {item.product_id} · {item.capability}
        </h2>
        <p className={muted}>
          {item.workflow ? `The product's ComfyUI workflow is ${item.workflow}. ` : ""}Other
          services run the same workflow where they can, or work from the prompt alone.
        </p>
        <p>
          Now runs on <strong>{current}</strong> ({item.source}).
        </p>
      </header>
      <MediaForm item={item} backends={list.backends} secretsReady={list.secrets_ready} />
    </>
  );
}
