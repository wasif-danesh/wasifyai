# ADR-0103: The implement, check, fix loop and undo belong to the Wasify engine

- **Status:** Accepted (2026-11-14, by the owner: "Accept all"). The owner's words behind it: "We don't need to copy code from the integration project but
  avoid the flaws in there." (2026-11-13)
- **Date:** 2026-11-14
- **Plan:** `docs/v2-coding-agent-start-plan.md`, sections 4 and 6 (stages C2 and C3). Measurements:
  `docs/spikes/coding-c0.md`, spike 10 and the review of the owner's test app.
- **Keeps:** rule 6 (anything slow is a job), rule 9 (usage), rule 10 (files through the storage interface),
  ADR-0068 (actions), stage J3 (long jobs kept in `action_jobs`).
- **Goes with:** ADR-0101, ADR-0102.

## Context

A coding agent should not stop at "I changed the code". It should run the project's check, read the failure, fix it
and try again, and the person should know afterwards whether the check passed.

The owner's test app did this with a "Stop" hook inside the Agent Server that ran a command the person typed. In a
real run it worked: the agent added a function, was refused with the failing output, fixed an old bug and was let
through. The review then found, by real runs:

- While the check ran, **the whole Agent Server stopped answering**: a 23 s check held an unrelated call for 22.7 s,
  and Stop only worked once the check had ended.
- A finish on the last allowed step **skipped the check**, and the chat still said finished.
- The check ran after a plain question too, and the agent **edited a file it was told not to touch** to get through.
- The gate was a script file beside the workspace. When it went missing, every later message was blocked.
- Nothing recorded whether the check had passed, and nothing limited the rounds.

For undo, the spike kept a second git store outside the workspace and used the workspace as its work tree. Edits,
deletes, new files, binaries, file modes and links were restored exactly, nothing of ours was left in the project, and
a checkpoint of this repository took 3 s. Ignored files, empty folders and the person's own git state were not
restored.

## Decision

**The loop**

1. **The Agent Server implements; the Wasify engine checks.** The check is a job of the Wasify engine, in its own
   process group, under the same sandbox profile as the agent's commands. It is never run by the Agent Server and
   never inside a hook.
2. **Done is a record we write** after a check passed. The Agent Server's "finished" only means the turn ended.
3. **The states of a turn** are: working; turn ended; checking; then one of passed, failed, not checked, could not
   check. A failure sends the command, its exit code and the end of its output back to the agent, up to three
   rounds. After the third the turn stops and says what still fails. The person can ask for another try.
4. **The check runs only when files changed** since the last pass, so a question costs nothing and changes nothing.
5. **The check is one command per workspace** to begin with. It is suggested from the project's files, shown to the
   person and can be changed. It is kept in our store, never in the workspace. Build, lint and test as separate
   steps come later, in the same table.
6. **A check that could not run is never "passed".** A missing command, a time limit reached (ten minutes by
   default) or a crash of the check gives "could not check". A turn stopped by the person or by the step limit gives
   "not checked".
7. **Stop ends a check at once**, because it is our process, and interrupts the Agent Server.
8. **Each check is a row**: workspace, session, turn, round, command, result, seconds, and the full output as a
   file. The result is one event on the stream, one card in the chat and one word in the session's header.
9. **Changed tests are shown.** If the agent changed or deleted a test file during the turn, the card lists the
   files. We make it visible; we do not forbid it.
10. **One function** serves the chat and scheduled runs (ADR-0105).

**Undo**

11. **A checkpoint store outside the workspace**, one per workspace, under the app's data folder, where the sandbox
    does not let the agent write. A checkpoint is taken before each turn of the agent. Undo takes one more
    checkpoint first, so an undo can itself be undone.
12. **The same store answers "did files change since the last pass?"** for rule 4.
13. **Three points are settled in stage C2, by an amendment to this ADR:** whether undo also restores the person's
    own git state (proposed: yes, its `HEAD` and index); whether a short list of ignored files such as `.env` is
    kept in checkpoints (proposed: no, and say so); and a project that holds another git folder inside it (not
    tried).

## Consequences

- The loop is code of ours with its own tests: every arrow of rule 3 against a fake Agent Server, then the review's
  real case with a real model.
- The loop's gate is measured in C3, when commands can run inside the sandbox: one refusal, one fix and one pass on
  the review's case; a two-minute check with every other call answering within a second; Stop within a second with
  no process left; a question answered with no file changed; three failed rounds ending in "needs you"; a missing
  command ending in "could not check"; the same rows from a scheduled run.
- Nothing of the gate is inside the agent's reach. The agent can still change the tests it is checked by; rule 9 is
  the answer to that.
- The checkpoint store grows with the project (88 MB for this repository after one checkpoint). When old checkpoints
  are dropped is decided in C2.
- The evaluation of spike 3 ran without the loop. Running it with the loop, on tasks whose first attempt fails, is
  the measure of what the loop adds.

## Amendment (2026-11-14, owner): the three open points of undo, settled in stage C2

Decision 13 left three points to stage C2 and proposed an answer to two. The owner's answer on 2026-11-14:
"Yes to the undo questions". The third was tried and settled by measurement (`docs/spikes/coding-cores.md`).

1. **Undo also restores the person's own git state:** where `HEAD` points, the commit of that branch, and the index
   (what was staged). Commits the agent made are not deleted; they stay reachable from the person's reflog. Other
   branches, tags, stashes and a merge in progress are not restored.
2. **Ignored files are not kept in checkpoints**, `.env` included, and the app says so: at the foot of the Changes
   tab, in the help, and by asking first. In "Ask me" a change to a file a checkpoint does not hold (one the project
   ignores, or one inside a `.git` folder) waits for the person's yes (ADR-0102, amendment of 2026-11-14).
3. **A project that holds another git folder inside it:** the inner project's files are kept as plain files, like
   any others, and are restored. The inner project's own git state is not saved.

Also settled while building it:

4. **A checkpoint before and one after every turn of a session that may change files.** What the turn changed is
   the difference of the two. A session in Plan takes none.
5. **Undo goes back one turn at a time, the newest that still stands first.** "Bring it back" returns the turn
   undone last, and only while no later turn has changed files.
6. **What the person changed themselves since the turn goes back with it**, because undo restores the whole
   project to the checkpoint. The answer says so, and "Bring it back" returns it: undo always takes a checkpoint
   first.
7. **The agent is told** with the person's next message that its last turn was undone.
8. **When old checkpoints are dropped is not decided.** Nothing is dropped yet; the store grows with the project.
