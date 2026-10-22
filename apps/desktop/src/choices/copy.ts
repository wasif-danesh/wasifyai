// SPDX-License-Identifier: AGPL-3.0-only
// The chat shelf (ADR-0086): the chat models worth offering. The lines about every other model are shared with the web
// (packages/ui/src/models/copy.ts).
import type { Tier } from "@wasifyai/ui";

export { COPY, type Copy, hostOf, plainFor } from "@wasifyai/ui";

export type ChatShelfItem = {
  repo: string;
  title: string;
  plain: string;
  /** the size of the usual 4-bit file, and the memory it needs, as measured (hub-shelf.yaml) */
  bytes: number;
  memoryGb: number;
  licence: string;
  tier?: Tier;
};

/**
 * The chat models worth offering (services/api/.../hub-shelf.yaml has the measurements). Sizes are the usual file's;
 * the exact files are read from Hugging Face when the download starts. Qwen3.5 9B joins once its checks pass (ADR-0078).
 */
export const CHAT_SHELF: ChatShelfItem[] = [
  {
    repo: "unsloth/Qwen3-4B-GGUF",
    title: "Qwen3 4B",
    plain: "Answers questions and writes well on most computers. A good place to start.",
    bytes: 2.5e9,
    memoryGb: 4,
    licence: "Apache-2.0",
  },
  {
    repo: "unsloth/Qwen3-8B-GGUF",
    title: "Qwen3 8B",
    plain: "Fuller answers than the 4B, a little slower. Needs 16 GB of memory or more.",
    bytes: 5e9,
    memoryGb: 6.5,
    licence: "Apache-2.0",
    tier: "also",
  },
  {
    repo: "unsloth/Qwen3-0.6B-GGUF",
    title: "Qwen3 0.6B",
    plain: "Tiny and very fast, for small computers. Simple answers only.",
    bytes: 0.4e9,
    memoryGb: 1,
    licence: "Apache-2.0",
    tier: "also",
  },
  {
    repo: "unsloth/gpt-oss-20b-GGUF",
    title: "gpt-oss 20B",
    plain: "A large model that shows its reasoning. Needs 32 GB of memory or more.",
    bytes: 11e9,
    memoryGb: 14,
    licence: "Apache-2.0",
    tier: "advanced",
  },
];

/** The chat model to offer first on a computer with this much memory. */
export function recommendedChat(memoryBytes: number | null): string {
  if (memoryBytes !== null && memoryBytes < 6e9) return "unsloth/Qwen3-0.6B-GGUF";
  if (memoryBytes !== null && memoryBytes >= 16e9) return "unsloth/Qwen3-8B-GGUF";
  return "unsloth/Qwen3-4B-GGUF";
}
