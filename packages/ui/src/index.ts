// The shared screens and the pieces they are made of. Apps import from here and give each screen the
// client it talks to the engine with (packages/client), so the same screen runs in the web app and in
// the desktop window.
export { cn } from "./cn";
export * from "./styles";
export { ACCEPTED_TYPES, MAX_UPLOAD_BYTES, fileProblem, firstFile, hasFiles } from "./pictures";

export { Button, buttonVariants } from "./components/button";
export { Chip } from "./components/chip";
export { Label } from "./components/label";
export { Notice } from "./components/notice";
export { Accent, PageHero } from "./components/page-hero";
export { PictureInput } from "./components/picture-input";
export { Bar } from "./components/progress-bar";
export { Spinner } from "./components/spinner";
export { Textarea } from "./components/textarea";
export {
  FailedNotice,
  JobMeter,
  ModeTabs,
  PromptField,
  WorkingCard,
} from "./components/create";
export { EnhanceButton, type EnhanceFn } from "./components/enhance-button";

export { type Picture, type PictureApi, usePicture } from "./hooks/use-picture";
export { usePictureEvents } from "./hooks/use-picture-events";
export {
  IMAGE_PRODUCT,
  type ImageFlowApi,
  type ImageRequest,
  useImageFlow,
} from "./hooks/use-image-flow";

export { CreateImage, type ResultActions } from "./image/CreateImage";
export { ImageForm, type ImageFormValue, MAX_PROMPT, SIZES } from "./image/ImageForm";
export {
  ImageWorkspace,
  type LoraOption,
  presetOf,
  RecipeList,
  type ImageWorkspaceProps,
  type WorkspacePreset,
} from "./image/ImageWorkspace";
export { ImageLibrary, type ImageLibraryProps } from "./image/ImageLibrary";
export { ChatScreen, type ChatScreenProps } from "./chat/ChatScreen";
export { ToolCard, type ToolCardProps } from "./chat/ToolCard";
export { Markdown, inline, parseBlocks } from "./chat/markdown";
export { type UseAssistantChatOptions, useAssistantChat } from "./chat/use-assistant-chat";
