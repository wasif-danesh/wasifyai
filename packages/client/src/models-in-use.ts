import { HttpError, type Transport, errorMessage } from "./transport";

/** One model the service uses (an admin chose it): what a person is shown on the web, with nothing to set up. */
export type InUseModel = {
  id: string;
  title: string;
  plain: string;
  ready: boolean;
};

export type InUse = {
  chat: InUseModel[];
  images: InUseModel[];
  video: InUseModel[];
  /** only when an admin put 3D on a provider (fal.ai, ADR-0095 K5); otherwise the 3D screen reads its worker */
  three_d?: InUseModel[];
};

export type ModelsInUseApi = { inUse(): Promise<InUse> };

/** The models the service uses for chat, images and video (read only; `GET /models/in-use`). */
export function createModelsInUseApi(transport: Transport): ModelsInUseApi {
  return {
    async inUse() {
      const res = await transport.fetch("/models/in-use");
      if (res.status === 401) transport.onUnauthorized?.();
      if (!res.ok) throw new HttpError(res.status, await errorMessage(res));
      return (await res.json()) as InUse;
    },
  };
}
