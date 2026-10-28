# UI improvement plan

From the audit of 2026-10-27 (`docs/ui-audit-2026-10-27.md`, pictures of the real window in
`docs/ui-audit/desktop/` and of the web app in `docs/ui-audit/`). The aim: one product that feels advanced and is
easy to use, where a person who has used one screen can use every other, and where the window and the web are
the same app (ADR-0087). The decisions that are new are ADR-0093 (Proposed); nothing here is built until the
owner picks the first stage.

## Principles (the whole app)

1. **One shell, on the window and on the web.** One side menu (its groups open one at a time, as before: the
   owner kept them over a flat menu with tabs in the bar, 2026-10-28); one top bar of one height on every screen
   (back and forward on the window, the title, the model button, the job tray, search, the theme); no breadcrumb,
   no "Group: Item" title, no second bar.
2. **One make screen.** Every tool that makes something uses the same three-part layout: **ask** (the prompt and
   the few controls that matter, "For experts" collapsed, the main button always visible), **stage** (where the
   result appears, with progress and the last result's actions), **recent** (a strip of the last things this tool
   made, from the one library). Images has it today; everything else gets it.
3. **One word for the main action: "Make".** "Make the picture", "Make the video", "Make the speech", "Make the
   song", "Make the 3D model". A verb of its own only where "make" would be wrong ("Write the lyrics", "Split the
   song", "Transcribe").
4. **Experts' fields behind "For experts".** Speed, Seed, Tempo, Key, Takes and the like leave the first screen
   (ADR-0073's rule, applied to every tool).
5. **One model control.** The top-bar button always names a real model (never a raw tag, never a hash) with a
   readiness dot, or says what to do ("Choose a speech model"); the picker is a dialog that does not cover the
   form; the first visit to a tool without a model shows one card with the recommended model, its size and one
   button (the ADR-0086 pattern, on every product).
6. **One library.** My creations is the only place things live; every "Your …" page goes, every in-screen
   "Made before" list becomes the recent strip, and both read the same library filtered by kind. Every creation
   opens to a detail view with its recipe, three actions and a menu for the rest, and the things made from it.
7. **One job system.** Work started on a screen shows progress on that screen (what, how far, how long, Stop) and
   in the tray; the tray lists every running job; a finished job's result is one click away from anywhere.
8. **Every state is designed.** Empty (what goes here and the first step), loading (skeletons), progress, error
   (what happened and what to do; never a path or a code), success (the result and its next actions).
9. **Say it once.** The heading is the title bar; the sentence under it is one line; instructions live in
   tooltips and placeholders; the keyboard hint is on the button.
10. **Picture, video, speech, song, recording, voice, notebook, model.** Those nouns, everywhere, and "make".
11. **No native controls.** Select, checkbox, radio, slider and the audio player come from `packages/ui`.
12. **Design before build.** Each stage starts with an HTML mockup under `docs/spikes/ui/` (as the Creative
    Studio and Styles ADRs did), the owner looks at it, then it is built from `packages/ui` components.

## The information architecture

### Home

The chat stays the home (ADR-0057). Under the box, instead of three random suggestions: **quick starts**, one
small card per product (Picture, Video, Speech, Song, Notebook, 3D, Motion graphics, Teach), each with one line
and the model's readiness, opening the tool with the box's text carried over when there is one. Below them,
**Running now** (when anything runs) and **Recent** (the last six creations). The box keeps three pills (Attach,
Mic, and the approval mode renamed "Ask me first" / "Just do it"); Thinking, Search and Servers move into a "+"
menu, and Servers is not shown at all until a server is connected. The web's Explore page becomes this home.

### The side menu

The groups stay as they are (the owner's decision of 2026-10-28, which closes decision 3): Notebook, Images,
Video, Voice and Music open one at a time with their tools under them, and Motion graphics, 3D model, Library,
Train models and Model hub follow. The magnifier in the menu goes: search is ⌘K and the box in the bar, and it opens
the Library. "Your images", "Your videos" and "Your music" stay as items of their groups until stage U8 replaces
them with the one Library and each screen's recent strip. Voices stays a page until U5 makes it a panel in Text to
speech. The names (decision 1) are untouched.

### The top bar

One row, 48 px, on the window and on the web: back and forward (window only; the web has the browser's); the
menu toggle; the screen's title (its group's name); the model button (a real name, a readiness dot, a chevron)
where the screen uses a model; at the right the job tray (a count and a bar, opening the Running now list),
search (⌘K, which also opens any tool by name), the theme. No second bar: a screen's own sub-title (a notebook's
name) is the title. The window keeps its traffic-light inset inside the same row.

### The make screen

```
┌ top bar: ‹ › ☰  Title · [● model ▾] ·                        tray · ⌘K · theme ┐
├──────────────────┬──────────────────────────────────────────────────────────────┤
│ ASK              │ STAGE                                                        │
│ prompt           │ the result (picture, player with waveform, video)            │
│ the 3 controls   │ progress while it is made: what, bar, how long, Stop         │
│ that matter      │ under it: three actions and a menu (edit, animate, save…)    │
│ [For experts ▸]  │                                                              │
│ ─────────────    ├──────────────────────────────────────────────────────────────┤
│ [ Make … ]  ⌘↵   │ RECENT: the last 12 of this kind, each opens, "See all"      │
└──────────────────┴──────────────────────────────────────────────────────────────┘
```

On a phone the three parts stack (ask, then stage, then recent) and the Make button is fixed. A tool with steps
(Dub, Audiobook, Lip sync, 3D, Teach) uses the same frame with a stepper in the ask column and "Back" in the bar.

## The flows, product by product

**Pictures.** Before: four menu items plus a Create tab in the bar, "Generate", Styles hidden behind "+", no
progress, an untitled strip, actions only after a make, the picker over the prompt. After: one screen, tabs Create
· Edit · Inpaint · Reference; "Make the picture"; Styles as a visible row (ADR-0091); progress on the stage with
the time it took last time; the result with Edit this, Animate this, Save a copy, and a menu (Use as reference,
Make again, Delete); a titled recent strip. Two steps to a picture, as today, and the next picture from the last
one is one click.

**Video.** Before: a card in a page, no stage, "Make my video", Extend's whole form in one card below the fold.
After: the make screen with tabs Create · Animate · Extend; "Make the video"; the clip plays on the stage; a
finished clip offers Extend and Save; the recent strip holds clips (Extend's grid becomes the strip plus a drop
zone); the tray names the clip.

**Speech.** Before: eight bare forms, a native select of 28 voices with no way to hear them, Speed and Seed on
the first screen, a two-line text box, "Made before". After: one screen, tabs Text to speech · Transcribe · Change
a voice · Edit speech; the ask column is a large text box with the voice chosen from a **voices panel** (built-in
and the person's own, each with a play button, "Make a voice" at the end with Describe or Clone inside it); "Make
the speech"; Speed and Seed under "For experts"; the stage is a player with a waveform and the words; the recent
strip lists takes with play, download, use again. Transcribe: drop zone in the ask column, the transcript on the
stage with times and copy.

**Studio (Dub, Audiobook, Lip sync).** Before: numbered sections that reveal one at a time in a narrow column,
each a page, two paragraphs of introduction, native selects. After: one screen with three tabs; a stepper in the
ask column (1 Recording, 2 Language, 3 Script, 4 Make); the stage shows the step's content (the script to read and
change, the chapters, the face and its consent); progress per chapter for the audiobook; the result plays on the
stage; "About 1 minute" instead of "About 1 minutes".

**Music.** Before: one long form with Tempo, Key, Seed and "Takes [1]" on the first screen; Lyrics a page; seven
actions under a take and eleven on a track; the web a dead end without a model. After: the make screen with a
prompt box from the start (a default model), style chips, an "Instrumental" switch, length in words, "Lyrics" as a
panel in the ask column (write them with the chat model or paste); Tempo, Key, Seed and "How many" under "For
experts"; "Make the song"; the stage is a player with the lyrics and three actions (Play, Save, Make again) with
the rest in a menu; tab Split for stems.

**Notebooks.** Keep the three panes and the start card. Before: eleven equal Studio cards, text-only outputs,
"Notebook: View notebooks" as a title, no renaming. After: the notebook's name is the title bar and renames in
place; the Studio's outputs are cards with a thumbnail and open in place; the eleven makers are grouped (Read:
report, study guide, flashcards, quiz; Show: mind map, infographic, slide deck, data table; Hear: audio overview;
Export: Word, PDF).

**Library.** Before: five places, two of them called Library, the menu's magnifier opening the wrong one. After:
one. Kind filters with counts, grid and table, search in any language, sort, multi-select with Save and Delete,
and a **detail view** (the thing large, its recipe, where it came from, three actions and a menu, what was made
from it, open the tool with this). Notebook outputs, 3D models, motion graphics and taught models join it
(ADR-0041 says they must be searchable anyway).

**Chat.** Before: six pills, "Asks first", a Servers notice as a dead end, no sign of running jobs, raw model
names, three suggestions. After: three pills and a "+" menu; "Ask me first" / "Just do it" with a tooltip; quick
starts under the box; a Running now line while a job runs; the card's "Go ahead" becomes "Make it"; a job's
progress in its card with Stop; the model button shows the model's display name and readiness.

**Teach, 3D, Motion graphics.** The same frame: a front door of cards whose state is honest (works here, needs a
step, not on this computer: one look each, with the reason on the card), a stepper for the steps with Back in the
bar, a run page with progress, pause and what it costs, the result as a card in the Library. Motion graphics keeps
its flow (say it, check the form, make it) and drops its own typeface and left column for the frame.

**Models and the picker.** Before: a table that clips its Use button and wraps the licence into four lines, a
hash as a name, a popover over the form. After: the picker is a dialog (the ADR-0086 one) with the same rows as
the Models page; the Models table gets a Name column with display names (a hash is a tooltip), a one-line licence
chip, and a readiness dot that the bar button shares; Advanced stays as it is.

**Settings.** Before: nine sections on one page, one Save button, native controls. After: grouped as General
(the person's name, the theme, updates) · Models (engines, finding, browsing, the token) · Privacy and sharing
(search the web, what leaves the computer) · Other apps (connections, tools from other apps) · Advanced (the
engine), with a left list of the groups, search, settings that save as they change, and "What this computer can
do" at the top (the self-test's facts in words).

## Shared components to build or change (`packages/ui`)

| Component | What | Replaces |
|---|---|---|
| `AppBar` | the one top bar for the window and the web: nav slot, title, model slot, tabs slot, tray, search, theme | `TitleBar` (window), the web's bar, the second bars, `PageHeader` placements |
| `MakeScreen` | the three-part frame with the fixed button and the phone stacking | the Images, Video, voice, music and Motion graphics page bodies |
| `Stage` | result area with the empty, progress, error and result states and a three-plus-menu actions row | ad hoc result areas |
| `RecentStrip` | the last N creations of a kind from the Library, with "See all" | "Made before", "Earlier", "Recent images", "Your videos" lists |
| `VoicesPanel` | voices with previews, built-in and own, "Make a voice" | the native select |
| `Select`, `Checkbox`, `Radio`, `Slider`, `Player`, `Field`, `Segmented`, `Stepper`, `EmptyState`, `ErrorNotice` (never shows a path), `Experts` (the collapsed section) | the design-system controls the guide names | native `<select>`, `<input type=checkbox/radio/range>`, `<audio>`, hand-made rows, the raw notices |
| `CreationDetail` | the detail view of one creation | nothing today |
| `QuickStarts` | the product cards under the chat box | the web's Explore cards |
| `JobTray` (change) | the list of running jobs with Stop, fed by `/actions/jobs`, on both apps | the one chip (web), nothing (window) |
| `ModelButton` and `ModelSelect` (change) | always a display name or a call to action, with a readiness dot; a dialog, not a popover | "Model for …", raw tags, the popover |
| `ActionsRow` | three actions and an overflow menu | the eleven-verb rows |

Copy: a `words.ts` with the nouns and verbs (picture, video, speech, song, voice, recording, make) that every
screen imports, and a test that greps the screens for "generate", "image", "asset" and "Takes".

## The stages

Each stage is a few days, ships on its own, and is checked the same way: the mockup first, then the real window
(`apps/desktop/scripts/ui-audit.sh` regenerates `docs/ui-audit/desktop/`) and the web against the mock
(`e2e/ui-audit.spec.ts`), the before pictures kept beside the after, the Playwright `@layout` specs in
`apps/web/e2e` extended for the screen, and the existing unit tests kept green.

| Stage | Days | What changes | How it is checked |
|---|---|---|---|
| **U0 Small fixes** | 1 | the typo on 3D; "About 1 minute"; the menu's magnifier opens My creations; the Models "Use" button inside the table and the licence on one line; "Library" heading on Your images becomes "Your images"; ⌘K opens search in the window; the Servers pill hidden until a server exists | the pictures of those five screens; the menu walk spec |
| **U1 Foundation** | 3 | the components above (`Select`, `Checkbox`, `Radio`, `Slider`, `Player`, `Field`, `Segmented`, `Stepper`, `EmptyState`, `ErrorNotice`, `Experts`, `ActionsRow`, `Stage`, `RecentStrip` shell), the `words.ts` and its test, a `/design` page on the web that shows every component in every state in both themes | the design page's screenshots in light, dark and phone; the words test; no screen changed yet |
| **U2 Shell** | 4 | the `AppBar` on the window and the web, the new side menu (11 entries, no groups), the breadcrumb and "Group: Item" titles gone, the tray as a list with Stop on both apps, ⌘K opening tools and the Library, the theme in the bar, the phone drawer | the menu walk spec; every route's picture on both apps; one bar height on every screen; the parity test |
| **U3 Pictures** | 4 | the `MakeScreen` built on Images (tabs, "Make the picture", Styles visible, progress on the stage, the actions row, the recent strip from the Library, the picker as a dialog) | a real make in the window; the Images e2e specs; before and after pictures |
| **U4 Video** | 3 | Video on the `MakeScreen` (Create, Animate, Extend as tabs; the stage plays the clip; Extend from a result) | a real clip in the window; the specs |
| **U5 Speech** | 5 | Speech on the `MakeScreen` with the `VoicesPanel`, the player with waveform, takes in the recent strip, Speed and Seed under For experts; Transcribe, Change a voice, Edit speech as tabs | a real speech and a real transcript in the window; the voice tests |
| **U6 Studio** | 4 | Dub, Audiobook and Lip sync on the frame with the `Stepper`; progress per chapter | a real dub and a real lip sync in the window |
| **U7 Music** | 3 | Music on the `MakeScreen` with a default model, style chips, lyrics as a panel, experts' fields folded, three actions and a menu, Split as a tab | a real song in the window |
| **U8 Library** | 4 | My creations as the one library: filters, sort, multi-select, the `CreationDetail` view with actions; the "Your …" pages removed and their routes redirected; the kinds that were missing added | the creations tests; every "Your …" link gone; detail from every card |
| **U9 Home and chat** | 3 | quick starts, Running now, Recent on the home; three pills and a "+" menu; the Explore page folded in; the pill and card words; display names on the model button; progress in a job card | the readme pictures regenerated; the chat specs |
| **U10 Notebooks, Teach, 3D, Motion** | 4 | the grouped Studio, outputs as cards, renaming in place; the honest front doors with Back in the bar; the stepper and run pages; Motion graphics on the frame | the notebook and training tests; the window |
| **U11 Settings and Models** | 3 | grouped settings with a list and search, settings that save as they change, "What this computer can do"; display names, a licence chip and readiness dots in Models | the window |
| **U12 Polish and access** | 3 | focus order, labels and contrast on every screen in both themes; reduced motion; forced colours; the final picture pass | an accessibility checker (decision 4), a keyboard-only walk of every screen, the pictures |

**Built:** U0 on 2026-10-27 (the seven fixes: `Model3d.tsx`, `minutesText` in `voice/format.ts`, the window's
`Sidebar.tsx` and `Shell.tsx`, `ModelsHome.tsx`, `ImageLibrary.tsx`, `composer-options.tsx`; the pictures in
`docs/ui-audit/desktop/` were taken again).

**Built:** U1 on 2026-10-27: `Select`, `Checkbox`, `RadioGroup`, `Slider`, `Field`, `Segmented`, `Stepper`,
`Experts`, `EmptyState`, `ErrorNotice` (with `plainError`), `Menu`, `ActionsRow`, `Player`, `Stage` and the
`RecentStrip` shell in `packages/ui/src/components/`, exported from the package; `packages/ui/src/words.ts` with
`words.test.ts`, which counts "generate", "image", "asset" and "Takes" in what the screens say and fails when a
count goes above its baseline (3, 36, 0, 4 on that day; a stage lowers the number when it rewrites a screen);
the web's `/design` page (`apps/web/components/design/DesignPage.tsx`) with every component in every state, its
`e2e/design.spec.ts` (`@layout` and `@visual` in light, dark and phone) and its pictures in `docs/ui-audit/`
(`design.png`, `design-dark.png`, `design-phone.png`). No screen changed. The unit tests are
`components/foundation.test.tsx`.

**Built:** U2 on 2026-10-27, changed 2026-10-28: `AppBar` (`packages/ui/src/app-bar.tsx`: nav, title, the
screen's header slot, the tray, search, the theme; 48 px on both apps), `titleOf` and `placesOf` in
`shell/menu.ts` (the bar's title and the search's places from `MENU_GROUPS`), the `SideMenu` with its groups (a
flat menu with the modes as tabs in the bar was built first and taken out again the next day: the owner wanted the
groups back), `SearchPalette` (⌘K: any tool by name, a creation by what it is about), `JobTray` with Stop (`jobLabel`
for the action ids), `useTheme` and `ThemeButton` shared by both apps; the desktop's `Shell.tsx` and the web's
`WebShell.tsx` use them, the web's `TopBar`, breadcrumb and `CommandMenu` are gone, the desktop's `TitleBar` is
gone; `PageHeader` claims the bar's title only when it carries one (`title`), so the Images, Video, voice, 3D and
chat screens keep the group's name as the title and put only the model button in the bar. The menu's names are
untouched (decision 1). The tray lists the engine's running actions on the desktop and the
clips being made on the web (the web has no `/actions/jobs` yet). Checked with the menu walk, the shared-screens
layout checks (one bar height on every screen), the unit tests of both shells and the pictures taken again.

**Changed 2026-10-28 (with U4):** the bar's title is a plain line, not an `h1`: every screen already has its own
`h1` (the tool's title, or the notebook's and chat's name in the bar), so each page now has one top-level heading
instead of two, and the home test's heading check is steady.

**Built:** U3 on 2026-10-28: `MakeScreen` (`packages/ui/src/components/make-screen.tsx`: ask, stage, recent;
the main button in view, the three parts stacked on a phone) and the Images screen rebuilt on it
(`image/ImageWorkspace.tsx`): "Make the picture" (`makeLabel`), the keyboard hint on the button, the Styles row in
view with the app's own checkbox and strength slider (ADR-0091), the seed under "For experts", the `Stage` with
its four states (progress with how long the last picture took, Stop, the plain-words error, the result with a
caption), three actions and a More menu on the result (`ActionsRow`), the `RecentStrip` titled "Recent pictures"
with See all to the library, and the model picker as a dialog (`ModelSelect`), on the window and the web. The
words test's baseline fell to "generate" 1 and "image" 28. Not in this stage: "Animate this" (it needs the
picture handed to Video, stage U4) and the strip reading the one Library (stage U8). Checked with the image unit
tests, the shared-screens specs, a real picture made in the window (`ui-audit.sh light image-make` pictures the
stage while it works and when it is done) and the pictures taken again.

**Built:** U4 on 2026-10-28: Video on the `MakeScreen` (`video/VideoWorkspace.tsx`), one screen for Create,
Animate and Extend, with the modes kept as the menu's items under Video (decision 3), not tabs in the screen.
The ask column holds the prompt, Length, Shape (Create only), the picture (Animate) or the chosen clip (Extend,
`video/ClipInput.tsx`: the clip, or a drop zone with "Add a video from this computer"), and My looks; "Make the
video" for all three. The stage plays the clip, with Extend this, Save a copy or Download, and a More menu
(Make it again, Use these words); progress says how long the last clip took. The recent strip lists the
finished clips; on Extend it is the list to choose from, so Extend's grid and its "Show older videos" are gone
(older clips: Your videos has Extend this in its dialog). "Animate this" on the Images stage hands the picture to
Animate (the window keeps it in the shell's state, the web in the tab's session storage, like Edit this), and
"Extend this" hands a clip to Extend from a Video screen or Your videos. The desktop tray now lists the clips
being made by their words, as the web's does (a clip from the Video screen is a run, not an action). The help
pages of the three actions say "Make the video". Checked with the video, Extend and image unit tests, the web's
video tests and the shared-screens specs (the two video pictures taken again, and the image-create and phone
notebook pictures, which still showed the screens from before U2 and U3), and a real clip made in the window
with LTX-Video 2B 0.9.5 (`ui-audit.sh light video-make`: Animate this from a picture, the stage while the clip was
made with the tray saying "1 running", the clip and its More menu, then Extend this; about two minutes for 5
seconds; pictures `video-animate-handed`, `video-making`, `video-made`, `video-made-more` and
`video-extend-chosen` in `docs/ui-audit/desktop/`).

**Built:** U5 on 2026-10-28: Text to speech, Speech to text, Change a voice and Edit speech on the `MakeScreen`
(`voice/SpeakWorkspace.tsx`, `TranscribeWorkspace.tsx`, `AudioToolWorkspace.tsx`, mounted by `MakeFrame` in
`voice/pages.tsx`; the modes stay the menu's items). Speech: the words in a large box, the `VoicesPanel`
(`voice/VoicesPanel.tsx`: your voices first, then the model's by language, each a radio with Play when it was
heard before, a cloned voice's recording, or "Hear it", which speaks the Voices screen's sample line; search from
nine voices; "Make a voice" opens the Voices tool in a dialog and chooses the new voice), the model's settings
(speed, seed) under "For experts", "Make the speech"; the stage plays the speech in the `Player`, which now draws
the recording's waveform as its seek bar (`useWaveform`, the browser's decoder; the plain bar when a file cannot
be read); Save a copy, Use these words, Change the voice, and in More: Edit the words and Delete (asks first);
Recent speech is the strip. Transcribe: drop or choose the recording, then "Transcribe"; the text with its times
on the stage with Copy, Save .txt, Save .srt and in More Save .vtt and Delete; Recent transcripts. The tools: the
recording from the app's `Select` and "Add a recording", the result players on the stage, "Made here before" (the
library's tracks of that kind). `OptionFields` and the web's model list use the app's controls (no native select,
checkbox or range), so Music gets them too; Split into parts is on the frame already (it shares the tool screen).
The help pages of speak, transcribe, convert, edit, split, design and clone are updated. Checked with the voice
unit tests (76), both apps' tests, the web specs (the five voice pictures taken again) and a real speech and
transcript in the window (`ui-audit.sh light speech-make`: Kokoro 82M, the waveform read from the real file,
"Make a voice", then Parakeet TDT 0.6B v3 writing the same words with their times; pictures `speech-voices`,
`speech-made`, `speech-make-a-voice`, `transcript-made`). Not in this stage: a voice preview that is not kept as a
speech (it needs an engine route: an owner decision), the Voices page leaving the menu (it is now also the "Make a
voice" dialog; the menu's names are decision 1), and the strips reading the one Library (U8).

**Built:** U6 on 2026-10-28: Dub a recording, Audiobook and Lip sync on the `MakeScreen` with the `Stepper` in the
ask column (`voice/DubbingWorkspace.tsx`, `AudiobookWorkspace.tsx`, `LipSyncWorkspace.tsx`; mounted by `MakeFrame`).
Dub: Recording, Language, Script, Voice; "Write the script" puts the lines on the stage to read and change, "Next:
the voice" asks whose voice, "Make the dub" plays the dub on the stage with its fit (Open Your music, Change the
script); progress follows "Speaking line i of n". Audiobook: Text, Chapters, Voice; the chapters are edited on the
stage (rename, join, remove, open to change the words), the voice comes from the `VoicesPanel` (Hear it), the
settings are under "For experts", and the stage follows "Chapter n of m, part j of k" (`stepProgress` in
`voice/format.ts`); the results play on the stage (the waveform up to 15 minutes). Lip sync: Picture, Voice, Make;
the stage shows the face with what was said about it before anything is made, then the video with the mark, Save
MP4, Rename (`NameDialog`, no `window.prompt` in the window) and Delete (asks first). The recording is chosen with
the shared `voice/SourcePicker.tsx`; no native select, checkbox or radio is left in the three (`RadioGroup` now
stays controlled when nothing is chosen). The model button is in the bar at every step. Each has a recent strip
(dubs, books and chapters, talking videos). Help pages of dub, audiobook and lip sync updated. Checked with the
voice unit tests, both apps' tests, the web specs (the three pictures taken again) and in the window
(`ui-audit.sh light studio-make`): a real portrait made with FLUX.2 klein 4B and turned into a 3 second talking
video with MuseTalk 1.5 (pictures `lipsync-face`, `lipsync-making`, `lipsync-made`). Not verified: a real dub on this
Mac. The engine refused it in words on the stage, twice: no voice model here speaks Spanish (Kokoro is English
only and no copying model is installed), and writing the script needs the voice separated, with Mel-Band RoFormer
not installed. Open: Dub lists languages that a model not on this computer speaks, and it separates the voice
whenever the speaker's voice is the default, which is before the person chooses the voice.

**Built:** U7 on 2026-10-28: Create music on the `MakeScreen` (`voice/MusicWorkspace.tsx`, mounted by `MakeFrame`).
The ask column: the model, Song or Sound effect (`Segmented`), the description with style chips that add or take
out a word, "No singing (instrumental)", the Lyrics panel with "Write them for me" (the chat model) or pasted words,
the length (`Slider`), and tempo, key, seed and how many under "For experts"; "Make the song" (or "Make the sound").
A model that does not say what it makes, or no model yet, still gets the song form, so the screen is never blank
(the web's dead end). The stage plays the piece with its waveform, its kind, length and model, its description and
lyrics; Save a copy, Make it again, Another take, and in More: Change a part (the editor opens on the stage), Split
into parts (Split opens with it chosen), the other formats, favourites, Rename (`NameDialog`) and Delete (asks
first). Recent music is the strip. Your music's list renames with the dialog too (no `window.prompt`). Sliders made
from a model's options show their name above them again. The words test's baseline for "Takes" fell to 3. Checked
with the music unit tests, both apps' tests, the web specs (the music picture taken again) and a real song in the
window (`ui-audit.sh light music-make`: a 30 second lo-fi instrumental with ACE-Step 1.5 Turbo, its More menu, then
Split into parts with it chosen and HTDemucs ready; pictures `music-ask`, `music-making`, `music-made`,
`music-made-more`, `music-split-handed`). Not in this stage: the Lyrics screen stays a page of its own (it is also
the panel), and the strip reads Your music, not the one Library (U8).

**Built:** U8 on 2026-10-28 (decision 2: yes). My creations is the one Library: the "Your images", "Your videos"
and "Your music" items are gone from the menu, their addresses open the Library filtered (`/creations?show=…` on
the web; the window's `library`, `videos` and `tracks` routes), and every "See all" lands there. The Library
(`creations/MyCreations.tsx`, `CreationsList.tsx`) has a filter and a count for each kind (a count says "+" while
there are more pages), the tools' own kinds (3D models, motion graphics, notebooks, taught models) as filters once
there is one, sort (newest, oldest, A to Z), Select with Save and Delete (asks first), "Add a recording" (Your
music's job), and the detail view (`creations/CreationDetail.tsx`): the thing large, its facts and recipe, **Made
from** and **Made from this** (each opening in place), and its tools as three actions and a menu (Edit this,
Animate this, Extend this, Make it again, Split into parts, Change the voice, Edit the words, Save a copy, Open in
its tool, Delete). Each app hands an entry to a tool with the hand-offs its make screens use (`navFor` with
`toolFor` in the window, `webCreationsNav` on the web). The engine keeps what a picture or a clip was made from:
`source_id` on `images` and `videos` (migration 0026 on Postgres; the SQLite file gets the column on first use),
in the summaries, and `?source=` on both lists; Edit, Inpaint and Reference keep the library picture they started
from (checked to be the person's own), Extend keeps its clip, Animate keeps the picture (`source_image_id`, kept
only when it is an id: the pictures are another product's), the assistant's actions pass the same, and a
replaced picture is not kept. Music uses the tracks' own `parent_id`. The creations client has `madeFrom`,
`remove` and `addRecording`. Checked with the engine tests (sources on memory, SQLite and real Postgres; the
migration up, down and up), the client, UI, desktop and web tests, the web specs (the Library's pictures taken
again, the three old pictures removed) and in the window (`ui-audit.sh light library-make`: a picture opened in
the Library, Edit this, a real edit with FLUX.2 klein 4B, then Made from and Made from this between the two;
pictures `library`, `library-detail`, `library-edit-made`, `library-made-from`, `library-made-from-this`). Not
checked for real: Animate and Extend keeping their source (unit and route tested; a clip takes minutes). Not in
this stage: things made before 0026 have no source; the shared `ImageLibrary`, `VideoLibrary` and `TracksPage`
components stay in `packages/ui` though no app opens them now.

About 44 days of work in thirteen stages; U0 to U8 are done, U9 next, then the products in the order a
new person meets them (Pictures, Video, Speech), with the Library before the home so the quick starts and the
recent strips have one source.

## What needs an owner decision

1. **Names.** "Pictures" for Images, "Speech" and "Studio" for the eight voice tools, "Teach" for Train models,
   "Models" for Model hub. The design guide already says picture and Teach; the menu does not.
2. ~~Removing the per-product libraries~~ Decided 2026-10-28 (owner): yes. "Your images", "Your videos" and
   "Your music" go; My creations is the one Library, each make screen keeps its recent strip with See all to the
   Library filtered to its kind, the old addresses redirect, and Your music's own jobs (add a recording, send a
   track to a tool) move to the Library's detail view. Stage U8.
3. ~~The menu without groups~~ Decided 2026-10-28: the groups stay, and a product's modes stay under them.
4. **An accessibility checker as a dependency** (`@axe-core/playwright`, MPL-2.0) for U12; the backlog (B2) has
   waited on this since the design system.
5. **The web's Explore page**: folded into the home (this plan), or kept as a marketing page outside the app.
6. **Mockup review before each stage**: the owner looks at the HTML mockup and says go; or the stages run on their
   own and the owner reviews the built screen.
7. **The chat box's pills**: three pills and a "+" menu (this plan), or the six pills as today.

## What this plan does not change

The engine, the actions, the routes the screens call (the Library view needs new list filters and the detail
view a few fields, nothing else), the chat thread's internals (assistant-ui), the notebook's three panes, the
consent and "leaves this computer" sentences, Motion graphics' say-it-then-check flow, and the tokens' contrast
rules.
