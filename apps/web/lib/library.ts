// The web app's clients for a person's finished images and videos, and their chats: the shared API (packages/client) on the
// BFF transport.
import {
  createAssistantApi,
  createCreationsApi,
  createImagesApi,
  createModel3dApi,
  createModelsInUseApi,
  createNotebooksApi,
  createTrainingApi,
  createVideoBuilderApi,
  createVideosApi,
  createVoiceApi,
  createWorkersApi,
} from "@wasifyai/client";
import { transport } from "./run-client";

export const webImages = createImagesApi(transport);
export const webVideos = createVideosApi(transport);
export const webAssistant = createAssistantApi(transport);
/** 3D models are made by an engine worker (ADR-0087): nothing to set up from the page. */
export const webModel3d = createModel3dApi(transport, { hosted: true });
/** Motion graphics is drawn by an engine worker (ADR-0087): nothing to set up from the page. */
export const webVideoBuilder = createVideoBuilderApi(transport, { hosted: true });
export const webNotebooks = createNotebooksApi(transport);
/** Train models: the teaching runs on an engine worker (docs/train-web-plan.md); an admin sets the trainers up there. */
export const webTraining = createTrainingApi(transport);
/** Speech on the web is served by hosted models: always ready, nothing to set up. */
export const webVoice = createVoiceApi(transport, { hosted: true });

export const imageDownload = (image: { id: string }) =>
  `/api/products/wasifyai-image/images/${image.id}/download`;
export const videoDownload = (video: { id?: string; videoId?: string }) =>
  `/api/products/wasifyai-video/videos/${video.id ?? video.videoId}/download`;
/** The engine workers, for admins: which models a worker has, and getting one onto it (ADR-0087, P5). */
export const webWorkers = createWorkersApi(transport);
/** The models the service uses for chat, images and video, shown by the "Select ... model" button (read only). */
export const webModelsInUse = createModelsInUseApi(transport);
/** My creations: every kind a person made, listed and searched (ADR-0040, ADR-0041). */
export const webCreations = createCreationsApi(transport);
