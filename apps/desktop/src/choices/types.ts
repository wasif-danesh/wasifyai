// SPDX-License-Identifier: AGPL-3.0-only
import type { Step } from "./steps";

/** Small per-person memory (the model chosen last time): `remember.ts`. */
export type Memory = { get(key: string): string | null; set(key: string, value: string): void };

/** What is installed in the shell and the engine that models run on, as a choice needs to know. */
export type EngineState = { installed: boolean; supported: boolean; bytes: number; name: string };

/** The engines a model may need before its files are of any use. */
export type Engines = {
  /** the image engine (ComfyUI): images, video, and one music model */
  image(): Promise<EngineState>;
  imageStep(): Promise<Step>;
  /** the language engine (llama.cpp): chat models that are files */
  language(): Promise<EngineState>;
  languageStep(): Promise<Step>;
};
