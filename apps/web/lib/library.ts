// The web app's clients for a person's finished images and videos, and their chats: the shared API (packages/client) on the
// BFF transport.
import {
  createAssistantApi,
  createImagesApi,
  createModel3dApi,
  createNotebooksApi,
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
/** Video Builder is drawn by an engine worker (ADR-0087): nothing to set up from the page. */
export const webVideoBuilder = createVideoBuilderApi(transport, { hosted: true });
export const webNotebooks = createNotebooksApi(transport);
/** Speech on the web is served by hosted models: always ready, nothing to set up. */
export const webVoice = createVoiceApi(transport, { hosted: true });

export const imageDownload = (image: { id: string }) =>
  `/api/products/wasifyai-image/images/${image.id}/download`;
export const videoDownload = (video: { id?: string; videoId?: string }) =>
  `/api/products/wasifyai-video/videos/${video.id ?? video.videoId}/download`;
/** The engine workers, for admins: which models a worker has, and getting one onto it (ADR-0087, P5). */
export const webWorkers = createWorkersApi(transport);
