# ADR-0105: Scheduled runs on a scheduler of our own, not on OpenHands' automation service

- **Status:** Accepted (2026-11-14, by the owner: "Accept all"). The choice of our own scheduler was the owner's the same day:
  "We will write our own optimised scheduler."
- **Date:** 2026-11-14
- **Plan:** `docs/v2-coding-agent-start-plan.md` (stage C6). Measurements: `docs/spikes/coding-c0.md`, spike 8.
- **Changes:** section 7 of `docs/v2-coding-agent-guideline.md` and the automation part of
  `docs/v2-cloud-and-engine-plan.md`, which both put Scheduled on OpenHands' automation service.
- **Keeps:** ADR-0088 (one job per person on the web), stage J3 (long jobs kept in `action_jobs`, stoppable, shown
  in Running now), ADR-0068 (actions), rule 7 (tenancy), rule 9 (usage), ADR-0103 (the check loop).
- **Goes with:** ADR-0101, ADR-0102, ADR-0104.

## Context

OpenHands' automation service was tried inside our sandbox (spike 8).

As a clock it was sound: one run per scheduled time, one catch-up run after it had been stopped or frozen across
two times, never a doubled run.

As a way to run coding work it does not fit:

- Its stock run builds a Python environment for every run and installs packages from the internet at run time
  (552 MB a run in the owner's test app, kept for 7 days). Inside our sandbox, with no internet, the run waited
  forever at "Installing dependencies".
- The run's script talks to the Agent Server by itself. It would pass by the Wasify engine, and so by the check
  loop, the usage records, the gateway that holds the model key and our rules.
- It copies each run's files to a fixed place in `/tmp`, which the sandbox had to allow.
- Two runs of one schedule overlap when a run takes longer than the gap.
- The server takes about 430 MB of memory beside the Agent Server.

What is left of it, on one person's computer, is a clock. A clock is small.

## Decision

1. **No automation service on the desktop in v1.** Scheduled is a part of the `wasifyai-code` product, inside the
   Wasify engine: no extra program, no extra port, no exception in the sandbox profile.
2. **A schedule is a row in the product's store**: who owns it, the workspace, the request in plain words, its rule,
   its time zone, whether it is on, and the next time it is due. Each time it comes due is another row: the time it
   stood for, what happened, and the session that ran.
3. **A rule is plain, not cron text.** The kinds in v1: once at a date and time; every so many minutes (five at
   least) or hours; every day at a time; on chosen weekdays at a time; every month on a day at a time (a day the
   month does not have means its last day). Times are the person's wall-clock times in the schedule's time zone.
   The next due time is one pure function, written with Python's own `zoneinfo`. **No new dependency.**
4. **Clock changes are decided, not left to chance.** A time that does not exist on the day the clocks go forward
   runs at the first moment after the gap. A time that comes twice when they go back runs the first time only.
5. **One timer serves every schedule.** It holds the next due time of each schedule that is on, sleeps until the
   earliest one, and wakes for nothing else. It reads the store only at start, when a schedule is made, changed or
   removed, and when one comes due.
6. **The sleep is never longer than a minute.** A computer that slept, a clock that was set, or a time zone that
   changed is then noticed within a minute. A wake that finds nothing due costs one comparison and no read of the
   store.
7. **A due time is claimed by writing its row.** The store allows one row per schedule and due time, so a second
   timer on the same store (two windows, or two servers on the web later) cannot run it twice.
8. **A missed time is caught up once.** When the app comes back and a schedule's time has passed, it runs once for
   the latest missed time if that time is less than a day old and the schedule says "run when missed". Older ones,
   and the earlier ones in a row of several, are recorded as missed. This is what the automation service did in the
   spike.
9. **One run of a schedule at a time.** If the earlier run is still going when the next time comes, that time is
   recorded as "skipped: still running". On the desktop, runs of different schedules wait in line and go one at a
   time. On the web the one-job-per-person rule applies.
10. **A run is the same function as a chat turn** (ADR-0103), started as a job of the kind that exists: it is in
    Running now, it can be stopped, and it ends in one of the four result words. "Run now" is the same function
    with the present moment as its due time.
11. **A run has no one to ask.** It works on a copy of the workspace, inside the sandbox, in the mode that needs no
    approval, and whatever would ask the person is refused and written down. Its result is offered as changes to
    look at and apply.
12. **The app must be open and the computer awake.** The screen says so beside every schedule, with the next time
    it will run. Starting at login and staying in the menu bar are part of stage C6. Waking a sleeping computer for
    a run is not in v1.
13. **OpenHands' automation service is kept in mind for later**: for runs set off by outside services such as
    GitHub or Slack, and for teams on a server. That would be its own ADR.

## Consequences

- Wasify ships two OpenHands parts, not three: the engine's packages and the catalogue.
- Cron text is not understood in v1. The few templates we offer are rewritten as plain rules by hand. If cron text
  is wanted later (to import other people's schedules), that is the moment to weigh a small library.
- The edge cases are ours: sleep, a changed clock, a changed time zone, the two clock-change days, months of
  different lengths, two timers on one store. Each has a test.
- **Gate for stage C6.**
  - The next-due function: every kind of rule, in three time zones, across both clock-change days and the ends of
    short months.
  - The timer on a pretended clock: fires on time; catches up once; records the rest as missed; skips a time whose
    earlier run is still going; two timers on one store give one run.
  - On the real app: a schedule fires within two seconds of its time while the app is awake; a nightly run on a real
    project for a week has no missed and no doubled run and changes nothing outside its copy.
  - Idle cost: no extra process, and a wake a minute that reads nothing.
- Starting at login needs a Tauri plugin. It is a new dependency, asked for when C6 begins.

## Amendment (2026-11-15): Scheduled as built in stage C6

The decisions above stand. What was settled while building, under the owner's standing yes of 2026-11-15:

1. **The copy (decision 11).** A run first takes a checkpoint of the project as it is, then writes what that
   checkpoint holds into `<app data>/coding/copies/<run>/<project's name>/`: the coding engine's own folder,
   inside the sandbox, outside the project. What the project ignores (`.env`, `node_modules`) is not in a
   checkpoint and so not in the copy. The copy is a project of its own in the store, marked as a copy and
   hidden from the person's list of projects, with the project's check, allowances and extensions.
2. **What a run may do.** Ordinary edits and commands run without a question. Whatever a chat in "Ask me"
   would ask about (a command that deletes, an install, a file Undo cannot put back, a picture or speech from
   Wasify AI) is refused and written down, unless the person allowed that kind for the project. The agent is
   told the step was not done and goes on. This is stricter than "Work on its own" in a chat, where a delete
   or an install is not asked: nobody is watching a run, and an install would open the way to the package
   indexes.
3. **Applying.** A run's changes stay in its copy until the person chooses "Apply to the project" or "Let it
   go". Applying takes a checkpoint of the project first, then writes each changed file only if the
   project's own file is still what the copy was made from; a file the person changed meanwhile is left as
   it is and named. It is refused while the agent is working in the project.
4. **Copies kept.** The copies of a schedule's five newest runs are kept; older ones nobody applied are let
   go. Deleting a schedule lets go of all of them.
5. **A schedule can name its model**; without one it uses the model a new session would.
6. **"Every so many minutes or hours" is counted from when the schedule is saved** (or changed).
7. **Routes and actions** are listed in `docs/desktop/coding.md`. Actions: `code.schedule.list`, `add`,
   `change`, `run`. Deleting a schedule, and applying or letting go of a run's changes, are on the screen
   only: a person looks first.
8. **Search.** A schedule is a kind of its own in the Library, "Coding schedule" (`code_schedule`), found by
   its name, its project, its rule in words and what it asks.
9. **The timer starts with the desktop engine** and serves from then on; it starts no process.
10. **Moved to the Browser tab's stage: starting at login and staying in the menu bar (decision 12).** Both
    are work in the Tauri shell that can only be judged in the real window, which the next stage opens
    anyway. Until then the screen says that schedules run only while Wasify AI is open, and has no switch
    for it.
11. **Not built:** waking the computer; a schedule moved to another
    project; a diff of each changed file before applying (the list names the files and what happened to
    each; the run's session can be opened to read what the agent did); the web.

Measured in `docs/spikes/coding-c6.md`.

## Amendment (2026-11-15): starting at login and the menu bar, as built

Decision 12's second half, moved here from stage C6 and built with the Browser tab:

1. **One switch on the Scheduled screen:** "Open Wasify AI when I log in, and keep it in the menu bar". Off
   unless the person switches it on. A Mac only; elsewhere it is not shown.
2. **At login** the app is started by a launch agent of the person's own, one plain file,
   `~/Library/LaunchAgents/ai.wasifyai.desktop.login.plist`, which starts the app once with `--hidden` and
   does not keep it alive. Whether the switch is on is that file being there. **No Tauri plugin was added**
   (this ADR expected one): the file is a dozen lines, and nothing is downloaded.
3. **In the menu bar** an item with "Open Wasify AI" and "Quit Wasify AI" (Tauri's `tray-icon` feature, for
   the Mac build only).
4. **Closing the window** then hides it; the engine and the timer go on. Quit ends the app as before. A
   click on the Dock icon brings the window back.
5. **Not built:** the newer macOS way of registering a login item (it shows the app by name in System
   Settings; the launch agent shows as a background item); waking the computer; the same on Windows and Linux.

Measured in `docs/spikes/coding-browser.md`.
