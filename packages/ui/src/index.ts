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
export {
  VIDEO_PRODUCT,
  type VideoFlowApi,
  type VideoRequest,
  useVideoFlow,
} from "./hooks/use-video-flow";
export {
  MAX_VIDEO_PROMPT,
  VIDEO_LENGTHS,
  VIDEO_SHAPES,
  VideoWorkspace,
  type VideoFormValue,
  type VideoWorkspaceProps,
} from "./video/VideoWorkspace";
export { VideoLibrary, type VideoLibraryProps } from "./video/VideoLibrary";
export { ChatScreen, type ChatScreenProps } from "./chat/ChatScreen";
export { ToolCard, type ToolCardProps } from "./chat/ToolCard";
export { Markdown, inline, parseBlocks } from "./chat/markdown";
export { type UseAssistantChatOptions, useAssistantChat } from "./chat/use-assistant-chat";
export { AddSources, SOURCE_ACCEPT, SOURCE_TYPES } from "./notebook/AddSources";
export { NotebookChat, CitationPill, type NotebookChatProps } from "./notebook/NotebookChat";
export { NotebookList, type NotebookListProps } from "./notebook/NotebookList";
export {
  NotebookWorkspace,
  type NotebookWorkspaceProps,
} from "./notebook/NotebookWorkspace";
export { SetupCard, type SetupItem } from "./notebook/SetupCard";
export { SourceGuide, type SourceGuideProps } from "./notebook/SourceGuide";
export { SourceViewer, splitAt } from "./notebook/SourceViewer";
export { useGuide } from "./notebook/use-guide";
export { SourcesPane } from "./notebook/SourcesPane";
export { StudioPane, type StudioPaneProps } from "./notebook/StudioPane";
export {
  AudioScriptViewer,
  FlashcardsViewer,
  InfographicViewer,
  MindMapViewer,
  OutputViewer,
  QuizViewer,
  SlidesViewer,
  TableViewer,
} from "./notebook/OutputViewers";
export { STUDIO_TILES, parseOutline } from "./notebook/outputs";
export { useOutputs } from "./notebook/use-outputs";
export { formatBytes } from "./notebook/format";
export { scopeIds, scopeLabel } from "./notebook/scope";
export { useNotebookChat } from "./notebook/use-notebook-chat";
export { useNotebookSources } from "./notebook/use-notebook-sources";
export { ModelPicker } from "./voice/ModelPicker";
export { OptionFields } from "./voice/OptionFields";
export { RuntimeCard } from "./voice/RuntimeCard";
export { SpeakWorkspace, type SpeakWorkspaceProps } from "./voice/SpeakWorkspace";
export {
  AUDIO_ACCEPT,
  TranscribeWorkspace,
  type TranscribeWorkspaceProps,
} from "./voice/TranscribeWorkspace";
export { COMMERCIAL_TEXT, STATE_TEXT, clock, modelOption, pickModel } from "./voice/format";
export { useVoiceModels } from "./voice/use-voice-models";
export { CONSENT_TEXT, VoicesWorkspace, type VoicesWorkspaceProps } from "./voice/VoicesWorkspace";
export { MusicWorkspace, type MusicWorkspaceProps } from "./voice/MusicWorkspace";
export {
  AudiobookWorkspace,
  TEXT_ACCEPT,
  type AudiobookWorkspaceProps,
} from "./voice/AudiobookWorkspace";
export {
  DubbingWorkspace,
  LANGUAGE_NAMES,
  SPEAKER_TEXT,
  type DubbingWorkspaceProps,
} from "./voice/DubbingWorkspace";
export {
  LipSyncWorkspace,
  MARK,
  PICTURE_TEXT,
  VOICE_TEXT,
  type LipSyncWorkspaceProps,
} from "./voice/LipSyncWorkspace";
export { TrackList, type TrackTool } from "./voice/TrackList";
export {
  AudioToolWorkspace,
  type AudioTool,
  type AudioToolWorkspaceProps,
} from "./voice/AudioToolWorkspace";
export { EditTrack, type EditTrackProps } from "./voice/EditTrack";
export { LyricsWriter, type LyricsWriterProps } from "./voice/LyricsWriter";
