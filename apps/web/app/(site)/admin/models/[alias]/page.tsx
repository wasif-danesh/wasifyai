import { Notice } from "@/components/Notice";
import { ModelForm } from "@/components/admin/ModelForm";
import { TextLink } from "@/components/ui/text-link";
import { apiGet } from "@/lib/api";
import { muted, pager } from "@/lib/styles";
import type { ModelList } from "@wasifyai/contracts";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ alias: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  return { title: `Model ${(await params).alias}` };
}

export default async function EditModel({ params }: Params) {
  const { alias } = await params;
  let list: ModelList | null = null;
  try {
    list = await apiGet<ModelList>("/admin/models");
  } catch {
    // shown below
  }
  if (!list) {
    return (
      <Notice tone="error" title="Couldn't load the model">
        The model gateway isn't answering right now.
      </Notice>
    );
  }
  const model = list.models.find((m) => m.alias === alias);
  if (!model) notFound();
  const current = list.providers.find((p) => p.id === model.provider)?.label ?? model.provider;
  return (
    <>
      <p className={pager}>
        <TextLink href="/admin/models">← Models</TextLink>
      </p>
      <header className="grid gap-[0.9rem]">
        <h2 className="text-step-1 font-semibold">{model.alias}</h2>
        <p className={muted}>{model.purpose}</p>
        <p>
          Now served by{" "}
          <strong>
            {model.provider ? `${current} · ${model.model}` : "nothing (not set up yet)"}
          </strong>{" "}
          ({model.source}).
        </p>
      </header>
      <ModelForm model={model} providers={list.providers} />
    </>
  );
}
