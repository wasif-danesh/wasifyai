// SPDX-License-Identifier: AGPL-3.0-only
// Meetings (ADR-0108): the shared screen on this window's engine. Models opens where the speaker
// model and the speech-to-text models are fetched; `#/meetings/<id>` opens one meeting (the Library
// links there).
import { Meetings, People, RecordMeeting } from "@wasifyai/ui";
import { useEffect, useState } from "react";
import { meetings, recorder } from "../meetings";
import { type Route, meetingPath, openNotebook, parseMeeting } from "../router";

export function MeetingsPage({ go }: { go: (r: Route) => void }) {
  const [id, setId] = useState(() => parseMeeting(window.location.hash));
  useEffect(() => {
    const onChange = () => setId(parseMeeting(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return (
    <Meetings
      key={id ?? "list"}
      api={meetings}
      initialId={id}
      onGetModel={() => go("models")}
      onOpenNotebook={(nid) => openNotebook(nid)}
    />
  );
}

/** Record (MT2): the shell records the microphone and the computer's sound; the meeting opens once it
 * is being made. */
export function RecordPage({ go }: { go: (r: Route) => void }) {
  return (
    <RecordMeeting
      api={meetings}
      recorder={recorder}
      onGetModel={() => go("models")}
      onOpen={(id) => {
        window.location.hash = meetingPath(id);
      }}
    />
  );
}

/** People (MT3): everyone named in a meeting; rename or forget them. */
export function PeoplePage({ go }: { go: (r: Route) => void }) {
  return <People api={meetings} onOpenMeetings={() => go("meetings")} />;
}
