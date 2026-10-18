// The web app's clients for a person's finished images and videos, and their chats: the shared API (packages/client) on the
// BFF transport.
import {
  createAssistantApi,
  createImagesApi,
  createNotebooksApi,
  createVideosApi,
  createVoiceApi,
} from "@wasifyai/client";
import { transport } from "./run-client";

export const webImages = createImagesApi(transport);
export const webVideos = createVideosApi(transport);
export const webAssistant = createAssistantApi(transport);
export const webNotebooks = createNotebooksApi(transport);
/** Speech on the web is served by hosted models: always ready, nothing to set up. */
export const webVoice = createVoiceApi(transport, { hosted: true });

export const imageDownload = (image: { id: string }) =>
  `/api/products/wasifyai-image/images/${image.id}/download`;
export const videoDownload = (video: { id?: string; videoId?: string }) =>
  `/api/products/wasifyai-video/videos/${video.id ?? video.videoId}/download`;
