# Code in Wasify AI: mockups of every screen

For the owner to approve before any screen is built (the rule of `docs/ui-improvement-plan.md`, principle 12, and of
`docs/v2-coding-agent-start-plan.md`, section 9). The design behind them is ADR-0101 to ADR-0105 and sections 2, 6 and 7
of the start plan. **Nothing here is built.** No file under `packages/`, `apps/` or `products/` was changed.

- **The mockups:** `docs/spikes/coding-mockups.html`. One file, opened from the file system. It fetches nothing: no
  network, no web font, no outside picture.
- **How to move:** the list on the left has every screen; the left and right arrow keys step through them. At the top:
  Light or Dark, the usual window (1100 × 760) or the smallest (720 × 520), and "All screens on one page".
  Many buttons inside a window lead to the screen they would open (the tabs, Stop, Undo, the menu's items).
- **One screen alone:** `coding-mockups.html?s=<name>&theme=dark&size=small&bare=1`, with a name from the table below.
- **What it is drawn with:** the app's own tokens (copied from `packages/ui/src/tokens.generated.css`), the real menu
  (`MENU_GROUPS` and `EXTRA_ITEMS` in `packages/ui/src/shell/menu.ts`), the one top bar (`AppBar`, 48 px), and the
  shapes of the real `Button`, `Badge`, `Notice`, `Segmented`, `Chip`, `EmptyState`, the progress bar, the chat's
  message, box and cards (`packages/ui/src/chat/thread/`), the Settings page and its Optional parts list
  (`apps/desktop/src/ComponentsPanel.tsx`: "Set up", "Not set up", "Repair", "Remove"). Icons are Lucide outlines,
  drawn inline.
- **The example used throughout:** a small shop website, `bakery-site`, and one request: add the opening hours to the
  home page and say "Closed today" on Mondays.

## The screens

47 screens in the nine groups that were asked for. The name in the first column is the screen's address.

### 1. Where coding lives, and the first screen

| Screen | What it shows |
|---|---|
| `start` | A new group, **Code**, in the side menu (Projects, Scheduled, Extensions). With no project yet, Projects asks for a folder and says what the agent may and may not do there, and what leaves the computer, before anything is read. |
| `start-chosen` | After the folder picker: what was found in the folder, the check suggested from its files, how much the agent asks (Plan, Ask me, Work on its own), and one button to open the project. |
| `projects` | The same menu item once folders have been opened: each project with its last session, the check's word and what waits for the person. |
| `session-new` | A project just opened: the question, three starting points that only fill the box, the mode in the box, the project's files beside the chat. |

### 2. The session

| Screen | What it shows |
|---|---|
| `session` | The agent at work. Its steps are quiet single lines (read, changed, ran) that open for the detail; a command's output is shown under it. The bar holds the project, the model, the session's state and the cost so far. The box holds the mode and Stop. |
| `session-done` | A turn that ended and was checked: one card in the chat, one word in the bar. The card lists the test file the agent changed. |
| `session-plan` | Plan mode: the agent only read, its answer is a plan, a card says nothing was changed, and one button carries the plan out. This is the whole session view of stage C1b. |
| `session-mode` | Choosing the mode: Plan, Ask me, Work on its own, each with one line that says what it means. |
| `session-cost` | The cost so far, opened: what it is made of and the limit for one session. |

### 3. The check

| Screen | What it shows |
|---|---|
| `check-setup` | The check command for a project, suggested from its files, and how it is changed. It can be tried at once. Time limit and rounds are under "For experts". |
| `check-running` | The check running after a turn: the card counts the time, the bar says "Checking", the tray counts one job, Stop ends it. |
| `check-results` | Not a real screen: the card for each of the four words (passed, failed, not checked, could not check) with the word the bar shows, a pass where the agent changed tests, and a question that changed nothing (no check runs; a quiet line says the last result stands). |
| `check-failed-round` | A failed round going back to the agent: the end of the output, "sent back to the agent", the fix, then round 2 of 3. |
| `check-needs-you` | "Needs you" after three failed rounds: what still fails, the test files the agent changed or deleted, and "Try 3 more rounds", "Undo this turn", "Change the check". |

### 4. Asking

| Screen | What it shows |
|---|---|
| `ask` | The approval card for a command a rule says must be asked: the command, the agent's reason, what it does, whether Undo covers it, the rule, then yes and no. While it waits the bar says "Waiting for you" and nothing else runs. |
| `ask-elsewhere` | The same question when the person is on another screen: a card under the bar, and "Waiting for you" on the project's row. |
| `ask-answered` | After a yes (the command ran) and after a no (the agent says so and goes on another way). The answered cards stay in the chat. |
| `refusal` | The model declines a request: a plain message with the model's own words. The turn ends, nothing was changed or run, and it is not shown as an error. |

### 5. The tabs

| Screen | What it shows |
|---|---|
| `files` | Files: the folder as a tree and a file to read. A dot marks what changed in this session. Reading only. |
| `changes` | Changes: one turn at a time, its files, each file before and after, and "Undo this turn". A test file is marked. |
| `changes-undone` | An undone turn: still in the list, marked, with "Bring it back". The chat keeps a line for it. The foot says what undo does not put back. |
| `terminal` | The person's own terminal, with the note about `ps`, `top` and `sudo`, and the same explanation in place when one of them is typed. |
| `terminal-processes` | The app's own list of what is running in the project (started by the person, the agent or a check), each with Stop. |
| `browser` | A browser of the person's own beside the chat, with "Add this page to the chat". |
| `preview` | The running result beside the chat: what is running, wide or phone size, load again, Stop, open in the person's own browser. |
| `preview-phone` | The same preview at a phone's width. |
| `preview-empty` | Before anything runs: what the preview does, the command it would run, one button. |

### 6. Scheduled

| Screen | What it shows |
|---|---|
| `scheduled` | The list: what each schedule asks, its project, its rule in words, the next time, what happened last, on or off, Run now. The note that the app must be open and the computer awake is at the top and beside every next time. |
| `schedule-new` | Making a schedule: the request in plain words or from a template, the five plain kinds of rule, a time zone, "Run when missed", and one sentence that says back what was set and when it next runs. |
| `schedule-rules` | Not a real screen: the "When" part with each of the five kinds chosen (once; every so many minutes or hours; every day; chosen weekdays; every month), and what happens when the clocks change. |
| `schedule-history` | One schedule's history with every outcome word (passed, failed, not checked, could not check, missed, skipped: still running, stopped), Run now, and the last run's changes waiting in its copy: look, apply or throw away. What the run would have asked is listed as refused. |

### 7. Extensions

| Screen | What it shows |
|---|---|
| `extensions` | The short list: a few of Wasify AI's own, a few public ones and what the person added, each on or off for the project chosen at the top. |
| `extension-detail` | One entry: when the agent uses it, the exact text it gives the agent (shown as plain text, with a note that it comes from outside), and on or off for each project. |
| `extension-add` | Adding one from a folder: what was found, its text, which project to switch it on for. |
| `extension-approve` | The approval for a plugin that brings a hook or a tool connection: everything it brings, in plain words, asked once. |

### 8. Settings › Optional parts

| Screen | What it shows |
|---|---|
| `settings` | The Coding engine as one more row of the list that exists today: not set up, with its size. |
| `settings-states` | Not a real screen: the row in every state: not set up with its size, setting up, set up, repairing, setting up failed, not available on this computer yet. |
| `settings-remove` | Remove asks first and says what stops and what is kept. |

### 9. The states that are easy to forget

| Screen | What it shows |
|---|---|
| `no-engine` | Code opened without its engine: one card with what the part is, where it comes from, its size and one button. |
| `engine-starting` | The engine starting when a project is opened (5 to 9 seconds): the session is laid out, the box says why it waits. |
| `error` | The engine stopped in the middle of a turn: what happened, what is true about the files, what to do; the raw text under "Details for experts". |
| `error-folder` | A project whose folder was moved, renamed or deleted. |
| `empty-scheduled` | An empty list: Scheduled with no schedule yet. |
| `empty-changes` | An empty list: the Changes tab before anything changed. |
| `long-output` | A command that printed 4,813 lines: one quiet line in the chat, only the end when opened, and the whole output beside the chat, loaded a part at a time, with "Save as a file". |
| `stopped` | A turn stopped by the person: who stopped it, what had changed, "Not checked", and what can be done next. |
| `cost-limit` | A session that reached its cost limit in the middle of a turn. |

## Choices for the owner

Where the ADRs left something open I drew one answer. Each is a question, with what I recommend.

1. **Is the menu group there before the engine is set up?** The start plan (section 5) says the menu item appears
   when the optional part is installed. I drew the group always there, opening on the set-up card (`no-engine`).
   *Recommend: always there.* Otherwise a person finds coding only by reading Settings. It needs one sentence of the
   plan changed.
2. **The group's name and items.** Drawn: **Code**, after Music, with **Projects**, **Scheduled** and **Extensions**.
   The five tabs live inside a session, not in the menu. *Recommend: as drawn.*
3. **"Project" or "workspace"?** The ADRs say workspace. The screens say "project" and "the folder you chose".
   *Recommend: project*, as the plainer word; the code can keep `workspace`.
4. **Where the mode is.** The brief put the mode in the header. I drew it in the box you write in, as a pill, because
   the home chat already keeps "Ask me first" and "Just do it" there and it is the same idea. The bar then has room
   for the project, the model, the check's word and the cost, also at 720 px. *Recommend: in the box.* If you want it
   in the bar instead, it fits at the usual size and gets tight at the smallest.
5. **The mode a new project starts in.** Drawn: "Ask me", chosen when the project is opened and changeable at any
   time. *Recommend: Ask me.* (Stage C1b has Plan only; the choice appears with C2.)
6. **One chip in the bar for the state and the check's word.** While something is happening it says Working,
   Checking, Starting or Waiting for you; otherwise it shows the last check's word. Clicking it opens the check.
   *Recommend: one chip.*
7. **The layout of a session.** The side menu steps aside when a project is open, as it does for a notebook; the
   chat is on the left (about 40%), the tabs on the right. At the smallest window there is one pane at a time and
   "Chat" becomes the first tab. *Recommend: as drawn.*
8. **"Start in a new, empty folder"** on the first screen, for someone who has no project yet (the starters for apps
   and games are not in v1). It would make a folder under `Documents/Wasify AI/Code`. *Recommend: keep it.*
9. **Files is for reading only.** A change goes through the chat, so every change belongs to a turn that can be
   undone. *Recommend: read only in v1.*
10. **Changes shows before and after in one column**, with Before, After and Both. Two columns side by side were not
    drawn; they are too narrow beside the chat. *Recommend: one column.*
11. **What Undo says it does not put back.** The foot of Changes says: files the project ignores (such as `.env`)
    and empty folders. That follows what ADR-0103 proposes for the amendment of stage C2. The person's own git state
    is not mentioned. If C2 decides otherwise, that line changes.
12. **No "don't ask again" on the approval card.** Every command a rule marks is asked each time. *Recommend: leave
    it out in v1.*
13. **The rules themselves have no screen.** The card names the rule ("Ask before deleting files"), but nowhere
    lists or changes the rules. *Recommend: a fixed list in v1, shown read-only from the mode menu; changing them
    later.* If you want a screen for them, it needs its own mockup.
14. **A question follows the person.** When the agent waits and the person is on another screen, the card appears
    under the bar, as connection approvals do today. *Recommend: yes.*
15. **The Browser tab is the person's.** The agent does not browse (ADR-0102 leaves its own browser tool to stage
    C4). The bridge I drew is "Add this page to the chat". *Recommend: the person's browser only in v1.*
16. **A cost limit per session.** ADR-0102 says the cost is counted and limited; no number is decided. I drew $2.00,
    changed from the cost in the bar, and "Raise the limit to $4.00 and go on" when it is reached. *Recommend: a
    default limit with the raise in place.* The number is yours.
17. **"Open Wasify AI when I log in"** sits as a switch in the note on Scheduled. It needs the Tauri plugin that
    stage C6 will ask for. *Recommend: there, and again in Settings › General.*
18. **A scheduled run's changes** wait in the run's copy with three buttons: Look at the changes, Apply to the
    project, Throw away. *Recommend: as drawn.*
19. **"Every so many minutes or hours" counts from when the schedule is saved.** ADR-0105 does not say where the
    count starts. *Recommend: from the save, and again from switching it on.*
20. **The short list of extensions.** The six names on the screen are stand-ins, not names from the catalogue: two
    of Wasify AI's own (the start plan's examples), three public skills, one plugin and one the person added. The
    list is yours to choose (start plan, section 10, item 3). *Recommend: begin with five or six, two of them ours.*
21. **A plugin is approved once for every project**; on and off stays per project. ADR-0104 says "approved once by
    the person". *Recommend: once.*
22. **"No check for this project"** is allowed in the check's dialog, with the line that every turn then ends "not
    checked". *Recommend: allow it; "not checked" is honest.*
23. **The row's name in Settings.** The other parts carry their tool's name ("Image engine (ComfyUI)"). I drew
    "Coding engine", and named OpenHands on the set-up card where it says where the part comes from. *Recommend:
    plain "Coding engine" in the list.*

## What I could not draw, or left out

- **The folder picker.** It is the system's own window (the Tauri dialog the app already has).
- **A screen for the rules** (see choice 13), and the list of a project's sessions (the pencil in the bar starts a
  new one; older sessions are reached from Projects, the Library and search, none of which is drawn here).
- **The Library card and the search result for a session, a schedule and an extension.** They must exist (every
  creation is searchable), but they belong to screens that exist already.
- **A scheduled run's own session.** It is the session view with a line saying it is a run on a copy; not drawn.
  Changing a schedule is the same form as making one; deleting one is the usual confirm dialog.
- **The quick-start card for Code on the home screen**, and the model picker's drop-down (it exists).
- **Moving parts:** hover, focus rings in use, the spinner's turn, the tray opened. The pictures are still.
- **Right to left, high contrast and touch sizes.** The mockup uses logical properties and the app's tokens, but I
  did not look at it in those modes.
- **Windows and Linux.** The window is drawn as on the Mac, which is all v1 has.
- **Real names from the extensions catalogue** and real sizes for the other optional parts: the catalogue and the
  manifests were not read for this; the rows around "Coding engine" are examples.

## How it was checked

- Opened from the file system in the installed Chrome, headless, with no network use by the page.
- 188 pictures: every one of the 47 screens in light and dark, at 1100 × 760 and at 720 × 520.
- An automatic check on all 188: nothing outside the window, nothing cut off by its parent, no button whose words
  are cut, no page that scrolls sideways, no script error.
- I looked at every screen at the smallest size in light and at most of them at the usual size in dark, and fixed
  what I found: names squeezed in the bar at 720 px, a dialog's buttons below the fold, a hint line too large, the
  menu not showing its current item when it scrolls, an opened output showing its start and not its end.
- Not done: the mockup was not put inside the real app window, and no person other than me has looked at it.
