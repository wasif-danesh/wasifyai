"use client";

import { type ModelChoiceState, chooseModel } from "@/app/(site)/admin/media/actions";
import { Notice } from "@/components/Notice";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { panel } from "@/lib/styles";
import { cn } from "@/lib/utils";
import type { ProductModels } from "@wasifyai/contracts";
import { useActionState, useId, useState } from "react";

const IDLE: ModelChoiceState = { status: "idle" };

const PRODUCT_TITLE: Record<string, string> = {
  "wasifyai-image": "Images",
  "wasifyai-video": "Video",
};

const VERB: Record<string, string> = {
  "image.generate": "create",
  "image.edit": "edit",
  "image.reference": "combine",
  "image.inpaint": "inpaint",
  "video.generate": "create",
  "video.animate": "animate",
  "video.extend": "extend",
};

/** What a model can do, in the words of the menu: "create, edit, combine". */
export function abilities(can: string[]): string {
  return can.map((c) => VERB[c] ?? c).join(", ");
}

/** The model one product's jobs use (ADR-0097, MV6). The ComfyUI host needs its files: an operator
 * fetches them with `python -m wasifyai_api.comfy_models`. */
export function MediaModelChoice({ choice }: { choice: ProductModels }) {
  const id = useId();
  const [state, action, pending] = useActionState(chooseModel.bind(null, choice.product_id), IDLE);
  const [model, setModel] = useState(choice.chosen);
  const picked = choice.models.find((m) => m.id === model);
  const title = PRODUCT_TITLE[choice.product_id] ?? choice.product_id;
  return (
    <form action={action} className={cn(panel, "gap-4")} aria-busy={pending}>
      <Field>
        <FieldLabel htmlFor={`${id}-model`}>{title} model</FieldLabel>
        <Select name="model" value={model} onValueChange={setModel}>
          <SelectTrigger id={`${id}-model`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {choice.models.map((m) => (
              <SelectItem key={m.id} value={m.id}>
                {m.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <FieldDescription>
          {picked ? `Can ${abilities(picked.can)}. ` : ""}
          Used for every {title} job that names no model. What it cannot do runs on{" "}
          {choice.models[0]?.title ?? "the first model"}.
        </FieldDescription>
      </Field>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={pending || model === choice.chosen}>
          Use this model
        </Button>
      </div>
      {state.status === "saved" ? (
        <Notice tone="ok" title="Saved">
          The next {title} job uses it. The ComfyUI host needs its files first.
        </Notice>
      ) : null}
      {state.status === "error" ? (
        <Notice tone="error" title="Not saved">
          {state.message}
        </Notice>
      ) : null}
    </form>
  );
}
