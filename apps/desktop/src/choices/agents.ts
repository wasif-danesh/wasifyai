// SPDX-License-Identifier: AGPL-3.0-only
// The person's own agent programs, Claude Code and Codex (ADR-0107, stage H2), for the Your agent tab of the Code
// model button and for Settings › Code. The programs are one optional part ("harness"); each signs in on its own
// page in the browser. Nothing here reads, keeps or sends a login or a token: the engine keeps only signed in or
// not, how, and the plan's name.
import type { CodeApi, CodeHarness, ComponentView } from "@wasifyai/client";
import type { AgentProgram, AgentSetup, AgentsApi } from "@wasifyai/ui";
import { installFraction } from "../engine";

/** The optional part that holds the programs. */
export const HARNESS_PART = "harness";

export type Parts = {
  get(id: string): Promise<ComponentView>;
  install(id: string, confirmBytes: number | null): Promise<unknown>;
  uninstall(id: string): Promise<unknown>;
};

/** The account each program signs in with, in words. */
const ACCOUNT: Record<string, string> = { "claude-code": "Claude", codex: "ChatGPT" };

const capital = (s: string) => (s ? s[0]?.toUpperCase() + s.slice(1) : s);

/** The plan's name, unless it only repeats who pays ("ChatGPT" on "your ChatGPT plan"). */
export function planName(h: CodeHarness): string {
  const plan = capital(h.plan);
  return plan && !h.plan_words.toLowerCase().includes(h.plan.toLowerCase()) ? plan : "";
}

export function programOf(h: CodeHarness): AgentProgram {
  return {
    id: h.id,
    title: h.title,
    payer: capital(h.plan_words) || `Your ${h.title} plan`,
    account: ACCOUNT[h.id] ?? h.title,
    signedIn: h.signed_in,
    plan: planName(h),
    signingIn: h.signing_in,
    page: h.page,
  };
}

export function setupOf(part: ComponentView | null): AgentSetup {
  if (!part) return { state: "unsupported", reason: "The agent programs are not offered here." };
  const s = part.status;
  switch (s.state) {
    case "not_installed":
      return { state: "not_installed", bytes: s.needs_bytes };
    case "installing":
      return {
        state: "installing",
        fraction: installFraction(s.progress),
        label: s.progress.label,
      };
    case "installed":
      return { state: "installed", version: s.version, bytes: 0 };
    case "failed":
      return { state: "failed", message: s.message };
    default:
      return { state: "unsupported", reason: s.reason };
  }
}

export function agentsApi(deps: { code: CodeApi; parts: Parts }): AgentsApi {
  return {
    async programs() {
      const part = await deps.parts.get(HARNESS_PART).catch(() => null);
      const listed = await deps.code.harnesses().catch(() => [] as CodeHarness[]);
      return { setup: setupOf(part), programs: listed.map(programOf) };
    },
    async setUp(bytes) {
      await deps.parts.install(HARNESS_PART, bytes || null);
    },
    async remove() {
      await deps.parts.uninstall(HARNESS_PART);
    },
    async signIn(id) {
      await deps.code.signIn(id);
    },
    async cancelSignIn(id) {
      await deps.code.cancelSignIn(id);
    },
  };
}
