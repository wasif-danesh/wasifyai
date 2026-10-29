// The shared screens and the pieces they are made of. Apps import from here and give each screen the
// client it talks to the engine with (packages/client), so the same screen runs in the web app and in
// the desktop window.
export { cn } from "./cn";
export * from "./styles";
export { ACCEPTED_TYPES, MAX_UPLOAD_BYTES, fileProblem, firstFile, hasFiles } from "./pictures";

export { Button, buttonVariants } from "./components/button";
export { Chip } from "./components/chip";
export { ConfirmDialog, NameDialog } from "./components/dialog";
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
// the foundation of the one make screen (ADR-0093, stage U1)
export { Select, type SelectGroup, type SelectOption } from "./components/select";
export { Checkbox } from "./components/checkbox";
export { RadioGroup, type RadioOption } from "./components/radio-group";
export { Slider } from "./components/slider";
export { Field, type FieldIds } from "./components/field";
export { Segmented, type SegmentedOption } from "./components/segmented";
export { Stepper } from "./components/stepper";
export { Experts } from "./components/experts";
export { EmptyState } from "./components/empty-state";
export { ErrorNotice, plainError } from "./components/error-notice";
export { Menu, type MenuItem } from "./components/menu";
export { type Action, ActionsRow } from "./components/actions-row";
export { Player } from "./components/player";
export { Stage, type StageState } from "./components/stage";
export { MakeScreen } from "./components/make-screen";
export { type RecentItem, RecentStrip } from "./components/recent-strip";
export { Skeleton } from "./components/skeleton";
export { Input } from "./components/input";
export { AVOID, NOUNS, type Noun, appearsHere, makeLabel, makingLabel, plural } from "./words";
// the one shell (ADR-0093, stage U2)
export { APP_BAR_PX, AppBar, ThemeButton } from "./app-bar";
export { type Theme, useTheme } from "./shell/theme";
export { type Place, SearchPalette } from "./shell/search-palette";
export { JobTray, TRAY_POLL_MS, type TrayJob, jobLabel } from "./shell/job-tray";

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
export { type VideoLook, looksOf, useVideoLooks } from "./video/Looks";
export { styleOptionsOf, useImageStyles } from "./image/styles";
export type { ChatScreenProps } from "./chat/ChatScreen";
export {
  ComposerOptions,
  useComposerOptions,
  type ComposerOption,
  type ComposerOptionsAvailable,
} from "./chat/composer-options";
export { Reasoning } from "./chat/Reasoning";
export { SearchSettings, type SearchSettingsProps } from "./chat/SearchSettings";
export { ConnectionsSettings } from "./connections/ConnectionsSettings";
export { YourKeys } from "./keys/YourKeys";
export { ExternalServers } from "./connections/ExternalServers";
export { ElicitationCards, FormCard, fieldsOf, useForms } from "./connections/ElicitationCards";
export { ServersPanel, type ExternalControl } from "./chat/servers-panel";
export { ApprovalCard, ApprovalCards, useApprovals } from "./connections/ApprovalCards";
export { AssistantHome, type AssistantHomeProps, greeting } from "./chat/AssistantHome";
export { conversationsChanged, useConversations } from "./chat/use-conversations";
export { ToolCard, type ToolCardProps } from "./chat/ToolCard";
export { Markdown, inline, parseBlocks } from "./chat/markdown";
export { AddSources, SOURCE_ACCEPT, SOURCE_TYPES } from "./notebook/AddSources";
export { CitationPill } from "./notebook/CitationPill";
export type { NotebookChatProps } from "./notebook/NotebookChat";
export { NotebookList, type NotebookListProps } from "./notebook/NotebookList";
export {
  NotebookWorkspace,
  type NotebookWorkspaceProps,
} from "./notebook/NotebookWorkspace";
export { SetupCard, type SetupItem } from "./notebook/SetupCard";
export { NotebookPlaceProvider, type NotebookPlace } from "./notebook/place";
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
export { STATE_TEXT, clock, modelOption, pickModel } from "./voice/format";
export { useVoiceModels } from "./voice/use-voice-models";
export { VoicesWorkspace, type VoicesWorkspaceProps } from "./voice/VoicesWorkspace";
export { MusicWorkspace, type MusicWorkspaceProps } from "./voice/MusicWorkspace";
export {
  AudiobookWorkspace,
  TEXT_ACCEPT,
  type AudiobookWorkspaceProps,
} from "./voice/AudiobookWorkspace";
export {
  DubbingWorkspace,
  LANGUAGE_NAMES,
  type DubbingWorkspaceProps,
} from "./voice/DubbingWorkspace";
export {
  LipSyncWorkspace,
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
export {
  AudiobookPage,
  DubPage,
  LipSyncPage,
  LyricsPage,
  MusicPage,
  SpeakPage,
  ToolPage,
  TracksPage,
  TranscribePage,
  VoicesPage,
  openInMusic,
  sendToTool,
  type AudioToolName,
  type Remembered,
  type Runs,
  type VoicePageProps,
  type VoiceTarget,
} from "./voice/pages";
export {
  CHAT_ITEM,
  EXTRA_ITEMS,
  MENU_GROUPS,
  type ItemResolver,
  type ItemView,
  type MenuGroupDef,
  type MenuItemDef,
  groupOf,
  placesOf,
  titleOf,
} from "./shell/menu";
export { type MenuLink, SideMenu, type SideMenuProps } from "./shell/SideMenu";
export type { RecentChat, Recents } from "./shell/RecentChats";
export { VideoBuilder, type VideoBuilderProps } from "./videobuilder/VideoBuilder";
export { Model3d, type Model3dProps } from "./model3d/Model3d";
export type { CandidateApi } from "./model3d/Candidates";
export {
  type Saved,
  type SaveAs,
  SaveAsProvider,
  extensionOf,
  fileNameFor,
  savedText,
  useSaveCopy,
} from "./save";
export {
  BackInBar,
  PageHeader,
  TopBarSlot,
  type WindowBar,
  WindowBarProvider,
} from "./window-bar";
export * from "./models";
export { Train, type TrainProps } from "./training/Train";
export { MyCreations } from "./creations/MyCreations";
export { CreationsList } from "./creations/CreationsList";
export { longEnough, toRow } from "./creations/model";
export { useCreationSearch } from "./creations/use-creation-search";
export type {
  CreationsNav,
  Entry as CreationEntry,
  Filter as CreationFilter,
  MakeScreen as MakeTarget,
  UseAction as CreationUse,
} from "./creations/model";
export { handDraft, takeDraft } from "./draft";
export { HomeStart, type QuickStartId } from "./chat/HomeStart";
