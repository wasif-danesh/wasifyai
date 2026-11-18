// SPDX-License-Identifier: AGPL-3.0-only
// The one setup card of a menu group, in place of a screen that cannot work yet (ADR-0109, stage FR4). Opening any
// item of a group that is not set up shows the group's card; its one button sets up every item of the group, and the
// screen opens when it is done. A screen that works (its parts are here, or the model in use is a cloud model on the
// person's key) opens as it is. Nothing is shown while the groups are read, and a failure to read them opens the
// screen: the card is a front door, never a wall.
import type { SetupGroup } from "@wasifyai/client";
import {
  type GroupId,
  GroupSetupCard,
  ModelSelect,
  type ModelSelectHandle,
  type SetupRun,
  useChoicesFor,
  useChoicesVersion,
} from "@wasifyai/ui";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { openYourKeys } from "./choices/keyed";
import { onComponentStatus } from "./components";
import { chatOffer } from "./setup-groups";
import {
  groupOfItem,
  readGroups,
  runOf,
  setupPorts,
  startSetup,
  stopSetup,
  watchRun,
} from "./setup-groups";

/** The model button that decides whether an item works on a cloud model, and opens the Cloud tab. */
const ITEM_CHOICE: Record<string, GroupId> = {
  "images.create": "images",
  "images.edit": "images",
  "images.inpaint": "images",
  "images.reference": "images",
  "video.create": "video",
  "video.animate": "video",
  "video.extend": "video",
  "voice.lipsync": "faces",
  model3d: "three_d",
  "voice.speak": "voice",
  "voice.audiobook": "voice",
  "voice.transcribe": "listening",
  "music.create": "music",
};

// read once for the window and shared by every gate; read again when a part changes
let cached: SetupGroup[] | null = null;
const readers = new Set<(g: SetupGroup[]) => void>();
export async function refresh(): Promise<void> {
  try {
    cached = (await readGroups()).groups;
    for (const r of readers) r(cached);
  } catch {
    // the engine is starting or this build has no setup route: the screens open as they are
  }
}

// one listener for the whole window, however many gates read the groups
let watching: Promise<() => void> | null = null;
function watchParts(): void {
  watching ??= onComponentStatus((_, s) => {
    if (s.state === "installed" || s.state === "failed") void refresh();
  });
}
function unwatchParts(): void {
  const w = watching;
  watching = null;
  void w?.then((stop) => stop());
}

export function useGroups(): SetupGroup[] | null {
  const [groups, setGroups] = useState<SetupGroup[] | null>(cached);
  useEffect(() => {
    readers.add(setGroups);
    if (readers.size === 1) watchParts();
    void refresh();
    return () => {
      readers.delete(setGroups);
      if (readers.size === 0) unwatchParts();
    };
  }, []);
  return groups;
}

export function useRun(groupId: string | null): SetupRun {
  const [run, setRun] = useState<SetupRun>(groupId ? runOf(groupId) : { state: "idle" });
  useEffect(() => {
    if (!groupId) return;
    setRun(runOf(groupId));
    return watchRun(groupId, setRun);
  }, [groupId]);
  return run;
}

/** Whether the model the item uses now is chosen and ready (a cloud model on a key counts). */
function useChosenReady(api: ReturnType<typeof useChoicesFor>, on: boolean): boolean | null {
  const version = useChoicesVersion();
  const [ready, setReady] = useState<boolean | null>(on ? null : false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the version is the trigger
  useEffect(() => {
    if (!on || !api) {
      setReady(false);
      return;
    }
    let gone = false;
    api
      .list()
      .then((l) => !gone && setReady(l.choices.some((c) => c.chosen && c.state === "ready")))
      .catch(() => !gone && setReady(false));
    return () => {
      gone = true;
    };
  }, [api, on, version]);
  return ready;
}

export function SetupGate({ item, children }: { item: string | null; children: ReactNode }) {
  const groups = useGroups();
  const group = item && groups ? groupOfItem(groups, item) : null;
  const state = group?.items.find((i) => i.id === item)?.state ?? "ready";
  const needs =
    group !== null && !group.explain_only && (state === "needs_setup" || state === "left_out");
  const choiceGroup = item ? ITEM_CHOICE[item] : undefined;
  const choiceApi = useChoicesFor(choiceGroup ?? "chat");
  const chatApi = useChoicesFor("chat");
  const covered = useChosenReady(choiceApi, needs && choiceGroup !== undefined);
  const run = useRun(group?.id ?? null);
  const picker = useRef<ModelSelectHandle | null>(null);
  const needsChat = !!group?.parts.some((p) => p.kind === "chat" && !p.set_up);
  const [chatBytes, setChatBytes] = useState<number | null>(null);
  useEffect(() => {
    if (!needsChat || !chatApi) return;
    let gone = false;
    chatApi
      .list()
      .then((l) => {
        const o = chatOffer(l.choices);
        if (!gone) setChatBytes(o ? o.downloadBytes + o.engineBytes : 0);
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [needsChat, chatApi]);

  const onSetUp = useCallback(
    (instead: boolean) => {
      if (group) void startSetup(group, instead, setupPorts(chatApi), () => void refresh());
    },
    [group, chatApi],
  );

  if (!group || !needs || covered === null || covered) return <>{children}</>;
  if (state === "left_out" && !group.key.covers) return <>{children}</>; // the screen says what is missing
  return (
    <div className="px-4">
      <GroupSetupCard
        group={group}
        chatBytes={chatBytes}
        run={run}
        onSetUp={onSetUp}
        onStop={() => stopSetup(group.id)}
        onKey={() => (choiceGroup && picker.current ? picker.current.open() : openYourKeys())}
      />
      {choiceGroup ? (
        <div className="mx-auto flex max-w-xl justify-center">
          <ModelSelect group={choiceGroup} api={choiceApi} handleRef={picker} />
        </div>
      ) : null}
    </div>
  );
}
