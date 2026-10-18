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


// The admin area and the caller's identity
export type Me = components["schemas"]["Me"];
export type AdminUser = components["schemas"]["AdminUser"];
export type AdminUserPage = components["schemas"]["AdminUserPage"];
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
export type EnhanceResult = components["schemas"]["EnhanceOut"];

// Search over My creations (ADR-0041)
export type SearchHit = components["schemas"]["SearchHit"];
export type SearchResponse = components["schemas"]["SearchResponse"];


export type MediaUploadResult = components["schemas"]["MediaUploadResult"];
