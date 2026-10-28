// The model button's display names (ADR-0093, stage U9): a model's tag in words a person reads.
import { describe, expect, it } from "vitest";
import { displayName } from "./copy";

describe("displayName", () => {
  it.each([
    ["qwen3.8:27b-mlx", "Qwen3.8 27B (MLX)"],
    ["Qwen3-8B-Q4_K_M.gguf", "Qwen3 8B (Q4_K_M)"],
    ["qwen3:latest", "Qwen3"],
    ["gemma4:e4b", "Gemma4 E4B"],
    ["mlx-community/Qwen3-30B-A3B-4bit", "Qwen3 30B A3B 4bit"],
    ["FLUX.2 klein 4B", "FLUX.2 klein 4B"],
    ["llamacpp:9ba9cc2b4e02463b933096090530aef679d534dd91ecc9afadfb2dbfdc59f3c5", "Unnamed model"],
  ])("%s reads %s", (tag, words) => {
    expect(displayName(tag)).toBe(words);
  });
});
