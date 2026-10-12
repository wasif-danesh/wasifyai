import type { components } from "./schema.gen";

export type { components };
export type SseEvent = components["schemas"]["SseEvent"];
export type NodeEvent = components["schemas"]["NodeEvent"];
export type TokenEvent = components["schemas"]["TokenEvent"];
export type InterruptEvent = components["schemas"]["InterruptEvent"];
export type JobProgressEvent = components["schemas"]["JobProgressEvent"];
export type ErrorEvent = components["schemas"]["ErrorEvent"];
export type DoneEvent = components["schemas"]["DoneEvent"];
export type RunRequest = components["schemas"]["RunRequest"];
export type ResumeRequest = components["schemas"]["ResumeRequest"];

// wasifyai-music's read API (product-provided routes)
export type SongSummary = components["schemas"]["SongSummary"];
export type SongDetail = components["schemas"]["SongDetail"];
export type SongPage = components["schemas"]["SongPage"];

// The admin area and the caller's identity
export type Me = components["schemas"]["Me"];
export type AdminUser = components["schemas"]["AdminUser"];
export type AdminUserPage = components["schemas"]["AdminUserPage"];
export type AdminSong = components["schemas"]["AdminSong"];
export type AdminSongPage = components["schemas"]["AdminSongPage"];
export type UsageReport = components["schemas"]["UsageReport"];
export type AuditEntry = components["schemas"]["AuditEntry"];
export type AuditPage = components["schemas"]["AuditPage"];

// Model access (admin)
export type ModelView = components["schemas"]["ModelView"];
export type ProviderView = components["schemas"]["ProviderView"];
export type ModelList = components["schemas"]["ModelList"];
export type ModelBinding = components["schemas"]["Binding"];
export type ModelUpdated = components["schemas"]["ModelUpdated"];
export type TestOutcome = components["schemas"]["TestOutcome"];

// Media access (admin)
export type MediaList = components["schemas"]["MediaList"];
export type MediaView = components["schemas"]["MediaView"];
export type MediaBackend = components["schemas"]["BackendView"];
export type MediaField = components["schemas"]["FieldView"];
export type MediaTestOutcome = components["schemas"]["MediaTestOutcome"];
export type SafeguardsStatus = components["schemas"]["SafeguardsStatus"];

// wasifyai-image's read API and the upload endpoint
export type ImageSummary = components["schemas"]["ImageSummary"];
export type ImagePage = components["schemas"]["ImagePage"];
export type UploadResult = components["schemas"]["UploadResult"];

// wasifyai-video's read API and the prompt enhancer every product shares
export type VideoSummary = components["schemas"]["VideoSummary"];
export type VideoPage = components["schemas"]["VideoPage"];
export type LipSyncSummary = components["schemas"]["LipSyncSummary"];
export type LipSyncPage = components["schemas"]["LipSyncPage"];
export type EnhanceResult = components["schemas"]["EnhanceOut"];

// Search over My creations (ADR-0041)
export type SearchHit = components["schemas"]["SearchHit"];
export type SearchResponse = components["schemas"]["SearchResponse"];

// wasifyai-tts: the voice catalog and a user's speech results (ADR-0042)
export type SpeechSummary = components["schemas"]["SpeechSummary"];
export type SpeechPage = components["schemas"]["SpeechPage"];
export type VoiceCatalog = components["schemas"]["VoiceCatalog"];
export type LanguageChoice = components["schemas"]["LanguageChoice"];
export type VoiceChoice = components["schemas"]["VoiceChoice"];

// wasifyai-stt: the languages to choose from and a user's transcripts (ADR-0043)
export type SpokenLanguages = components["schemas"]["LanguageCatalog"];
export type SpokenLanguage = components["schemas"]["SpokenLanguage"];
export type TranscriptSummary = components["schemas"]["TranscriptSummary"];
export type TranscriptDetail = components["schemas"]["TranscriptDetail"];
export type TranscriptPage = components["schemas"]["TranscriptPage"];
export type MediaUploadResult = components["schemas"]["MediaUploadResult"];
