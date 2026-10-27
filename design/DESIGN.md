# Wasify AI design

The single source of the look of the web app and the desktop app (ADR-0081). **Everything that is a value (colour, type, shape,
spacing, depth, motion) is defined once, in the tokens block at the end of this file.** `pnpm design:build` turns it into
`packages/ui/src/tokens.generated.css` and `tokens.gen.ts`; nothing else may define a colour, size, radius, shadow, duration or font.

- **Change the look:** edit the tokens block, or swap in another template with `pnpm design:use <name>` (templates are in
  `design/themes/`; each holds only a tokens block). Then `pnpm design:build`. The build refuses a template that is incomplete,
  has a colour outside sRGB, or fails a contrast rule.
- **What a template cannot change:** layout and screen flow, the anatomy of components, the icon set (Lucide), illustrations and
  the product art, the wording beyond the rules below. Those are code and need a pull request (and an ADR for a new component
  family or layout).
- **Version:** the template's `meta.version`. A breaking change to a token name is noted in `design/CHANGELOG.md`.

## Principles

1. **Plain words, calm screens.** The person sees only what they can answer. Anything technical lives behind a collapsed
   "For experts" panel (ADR-0073). One main action per screen.
2. **The app chooses; the person confirms.** Defaults come from measurement (a size, a time estimate), shown in words.
3. **Say what will happen, what it costs, and what leaves the computer,** before the click: sizes of downloads, minutes of work,
   anything sent elsewhere.
4. **Never lose the person's work.** Long jobs continue if they leave the screen; destructive actions ask first; there is always
   a way back.
5. **Accessible by default.** Contrast, keyboard, focus, reduced motion and right-to-left are part of every component, not a later pass.

## Voice and tone

- Plain words, sentence case, short sentences, contractions are fine. Say "make" not "generate", "picture" not "asset",
  "magic word" not "trigger token" (the experts' words stay in "For experts").
- A button says what it does ("Make the picture", "Save a copy"), not "Submit" or "OK".
- **An error says what happened and what to do next,** never a code or a stack trace: "That file is too large. Use one under 300 MB."
- Use the product words consistently: *My creations*, *My models*, *Video Builder*, *Motion graphics*, *Make a 3D model*, *Teach*.
- English only in v1; the layout must still survive longer strings and right-to-left (use logical properties: start and end).

## Components: which to use

| Need | Use |
|---|---|
| The main action | `Button` (filled, accent). One per area. |
| A quieter action | `Button` secondary or outline; destructive uses the `danger` token and confirms in a dialog |
| Pick one of a few | `RadioGroup` (stacked, with a line under each) or `Segmented` (side by side, one always chosen); of many, `Select`; with search, `Command` |
| A yes or no | `Checkbox`; a setting that applies at once, `Switch` |
| A number on a range | `Slider`, with the value in words beside it |
| A labelled control | `Field`: the label, the control, one hint line, the error |
| Settings only an expert needs | `Experts`: a collapsed "For experts" section, closed by default |
| Where a person is in a flow | `Stepper` |
| Where a result appears | `Stage`: empty, working, error and result, with its actions |
| What can be done with a thing | `ActionsRow`: three buttons and a `Menu` for the rest |
| The last things a tool made | `RecentStrip`, fed by the one library |
| Audio | `Player` (the app's own controls), never the browser's |
| A message about the page | `Notice` (info, warning, error) at the top of the area it concerns; a toast (`Sonner`) only for a result of an action |
| Something takes time | a `ProgressBar` with words (what, how far, how long); the work continues if the person leaves; on a make screen, the `Stage`'s working state |
| A list of things the person made | cards in a grid with a thumbnail, title and kind filter; the library search is one box |
| An area with nothing in it yet | `EmptyState`: what goes here and the first step |
| An error | `ErrorNotice`: what happened in plain words (`plainError` strips paths, addresses and codes), what to do, the raw text under "Details for experts" |

Always build from `packages/ui` and `apps/web/components/ui`; do not style a native element by hand, and do not use a
native `<select>`, checkbox, radio, range or `<audio>` in a screen: the components above replace them. Every component in
every state, in both themes, is on the web's `/design` page (`apps/web/components/design/DesignPage.tsx`); a new component or
state is added there in the same change. The words a screen uses for what a person makes come from `packages/ui/src/words.ts`
("picture", "make"); `words.test.ts` keeps "generate", "image", "asset" and "Takes" from creeping back in.

## States every component has

Default, hover, focus-visible (a ring of 2 to 3 px, 3:1 against its neighbours), active, disabled (with a reason when it is not
obvious), loading (a skeleton or a spinner, never a blank), empty (says what goes here and how to start), error (what and next step),
success (confirms, then gets out of the way).

## Motion

Short and quiet: entrances ease out (`--ease-out-soft`); nothing moves for more than a second except real progress.
`prefers-reduced-motion` switches every animation and transition off (`packages/ui/src/tailwind.css`, checked by the build).

## Accessibility rules

- WCAG 2.2 AA: text 4.5:1, large text and interface parts 3:1, in light **and** dark. The contrast rules in the tokens block are
  checked on every build.
- Every control has a name; a picture that carries meaning has text; meaning is never by colour alone.
- A target is at least 24 px, and 44 px on touch. Everything works by keyboard, in a sensible order.
- Forced-colors and high-contrast modes keep controls visible (borders, focus rings use system colours there).

## Language

Logical CSS properties (`ms-`, `me-`, `ps-`, `pe-`, `start`, `end`) instead of left and right. No fixed-width text boxes. Fonts are
files we ship with their licences recorded; the desktop never fetches fonts from the network.

## The shell (ADR-0093, stage U2)

One side menu of eleven entries, each one click to a tool; a product's modes are tabs in the top bar, never a second
level of the menu. One top bar (`AppBar`, 48 px) on the desktop window and on the web: the app's navigation buttons, the
entry's name as the title, the screen's model button (put there with `PageHeader`), the tabs, then the job tray, search
(⌘K, `SearchPalette`) and the theme. No breadcrumb, no second bar, no "Group: Item" title. A screen that has a title of
its own (a chat, a notebook) passes `title` to `PageHeader` and the bar shows that instead.

## Screen patterns (written before the screens are built)

- **Long work never blocks the window (ADR-0086 amendment, 2026-10-25).** A model download asks first in a dialog (files, size, licence) that closes the moment the person agrees; the work goes on in a **tray** at the top right, under the top bar, on every screen: name, percentage, a thin bar, a stop button; queued rows say "Waiting"; a finished row says "Ready" and leaves after a few seconds; a failed row stays with its reason and "Try again". The tray is a labelled region with a polite live line; it never takes focus and the page behind stays usable.

- **The model button is in the top bar (ADR-0086 amendment, 2026-10-24).** Every screen that makes something with a model puts its "Select ... model" button at the left of the page's top bar, as the chat, Images and Notebook screens do; the page's other tools (the library link, a mode tab) go at the right. In the app window that bar is the window's own (`PageHeader`); on the web it is a bar at the top of the screen's area (`TopBarSlot`, same `PageHeader` call). A screen never puts its model button in the body or gives it a "Model" label. A second picker on one screen (for example editing a track on the Music screen) stays in its own panel. On the web the button on Image, Video, Chat and 3D is read only: it names the model the service uses and says whether it is ready.

- **Chat (the assistant; built on assistant-ui, ADR-0082, `packages/ui/src/chat/thread/`):** a title bar (name, rename, delete) only for a saved chat; while empty, the greeting, the box and three
  suggestions under it, which put their text in the box and never send; afterwards the thread (at most `max-w-3xl`, a gap
  between messages) and the box at the bottom. **The box is one element for the whole chat** (Enter sends, Shift+Enter is a new
  line, `dir="auto"`, up to 4,000 characters); while an answer arrives Stop sits beside Send, which waits. The person's message
  is a right-aligned bubble in `accent`, text `dir="auto"`; the assistant's is plain text with no bubble. Under a finished
  reply: Copy. "Thinking…" shows until the first word. A failure is a `Notice` (error) at the end of the thread with one button:
  Try again, or Choose a model. A tool is a bordered card inside the reply (a picture being made, then the picture with "Open in
  the library"; a music player; search results; a waiting question with `confirm_action`, which CU2 makes answerable). Markdown
  is formatted by streamdown under the rules in `markdown/md-config.ts`: raw HTML is shown as text, only an absolute http(s)
  address is a link, no picture loads unless its origin is allowed, diagrams use the strict level with no HTML labels. Code,
  maths and diagrams load on first use and work offline. The thread itself is not a live region (it would read every chunk);
  a hidden status says "The assistant is answering" and then "Answer ready", and the finished answer is read once from a log.
  **The options bar** (`ComposerOptions`, ADR-0083) sits inside the box, left of Stop and Send: pill buttons with an icon and a word, off by default, pressed
  = `accent` fill and a `primary` border, 32 px high (44 px on a touch screen), each named by what it does and why it is disabled. A button is there only when
  it can work (Thinking only for a model that can think). **Thinking** is a closed `<details>` under the answer ("Thinking", with a spinner while it
  arrives), plain text, never markup; while a thinking answer is pending the screen says it takes longer.
  **Search** is a pill like Thinking. The first press shows a card (`accent` fill) that names the service and what is sent and has "Allow search" and "Not now"; a service
  that needs a key says so and opens Settings. Under an answer that used the web, **source cards** list each result: the title as a link (opens in the person's own browser;
  only http and https are links), the site at the end of the line and a two-line snippet in `muted-foreground`.
  **Read aloud** is a speaker icon button in the action row under a finished reply (beside Copy and Answer again; `muted-foreground`, `accent` fill while it works, 36 px or 44 px on a touch screen), named "Read this reply aloud"
  and, while it works, "Stop reading aloud" (`aria-pressed`). While it works it shows a status line next to it in `muted-foreground` text-xs: a pulsing `primary` dot (still when the person prefers less motion) and "Getting ready to read…",
  "Reading aloud" or "Reading aloud · 2 of 3"; the icon is a spinner before the first sound and a square (stop) after. It never plays by itself. A problem or note is the same `accent` card as Mic's under the reply; with no voice installed the first press
  shows "Set up read aloud" (name, licence, source, languages, size, "Download" and "Not now").
  **Mic** (dictation) is a pill too ("Mic"; while it listens "Stop", pressed). Pressing it shows a card (`accent` fill) above the box: a pulsing `destructive` dot (still
  when the person prefers less motion), "Listening with <the microphone's name> · 0:07" in a status line, and a "Cancel" that throws the clip away; "Stop" is the pill
  itself. Then "Transcribing…", and the words land in the box after what is there, to be changed and sent by the person; they are never sent by themselves. A problem
  (the microphone is turned off for this app, none was found, nothing could be heard, the speech model is busy) is an alert card with one sentence and "Close". With no
  speech model the first press shows the **setup card** instead of recording: what it is, the model's name and licence, where it comes from, the size, and one "Download 956 MB"
  button with "Not now"; nothing is fetched before the click. The pill is absent where the engine cannot write words down (the web without a hosted transcription model).
  **Attach** (a paperclip, first in the bar) opens the file picker; drops and pastes work on the box. Files wait **above the words** as chips: a 56 px thumbnail for a picture, a rounded chip (name, then a muted line:
  "12 pages", "3,200 characters", "Only the start is used") for a document, a spinner while it goes up, a `destructive` border and the engine's sentence when it is refused, a round remove button on the corner. After sending they sit
  above the person's message, right-aligned. Everything is a token; at 320 px the chips wrap.
  **Versions:** a message with more than one version (an edit, or an answer made again) shows "2 / 3" with previous and next arrows under it; the person's
  messages have a pencil ("Edit message") that opens an edit box in place (Cancel, Send), and replies have "Answer again". **The confirm card** (`ConfirmActionCard`) is an
  `accent` panel, 28 rem wide at most: the action's name, a line, up to four parameters as plain text, then "Go ahead" and "Not now"; once answered it says what happened.
  Everything is a token; at 320 px nothing scrolls sideways (a wide table, code block or diagram scrolls inside its own frame).
- **Notebook chat (the same thread primitives, ADR-0082 stage CU4):** the old layout kept: a slim bar above the thread
  (conversation switcher, "New chat"), then, while empty, the add-sources screen or the guide and one line ("Ask a question about your sources. Answers cite the passages
  they came from."), then the box. **The box** is the assistant's with two differences: it is named and says "Ask about your sources", and its bar starts with the
  **scope** ("12 of 14 sources, 2 being read", `text-xs`, `muted-foreground`, truncates) and carries the model chip before Stop and Send; no options bar. An answer is
  the assistant's plain text with, above it, one `text-xs` line with a search icon ("Searched 3 sources, found 5 passages"), while it waits "Reading your sources…",
  and **citation pills**: `[n]` becomes a small round `primary`-tint button (20 px, `font-semibold`, `text-2xs`) named "Source n: title", which opens the passage in the
  sources pane; a label that is not one of the answer's passages stays as text, and a label inside code or a link is left alone. Under a finished answer: Copy (icon) and
  "Save as note". There is no Edit, "Answer again" or version picker (a notebook's conversation is a line). A model's thinking is the same closed "Thinking" `<details>`
  under the answer. A failure is the same `Notice` with Try again or Choose a model.
- **Teach (training):** a front door with three cards; three steps (add examples, check, train) then "use it"; the app picks the
  settings and shows "Quick" or "Better" and a time (ADR-0073).
- **Agent:** a goal box, starting points, a live feed, approvals as inline cards, Stop always visible, the result saved as a report.
- **Video Builder and Motion graphics:** describe, preview three stills, change it in words, render; the code view is closed.
- **Make a 3D model:** pick a starting point, check the picture, "about 5 to 25 minutes", a viewer with orbit, the result as a card.
- **Setup and download cards:** what it is, where it comes from, the size, the licence, one button; nothing is fetched without the click.

## The tokens

Three tiers. **Primitives** are raw values. **Semantic tokens** are roles (`color.accent`, `radius.md`), each with the CSS variable
it becomes. **Components use only the semantic tokens.** A colour is `oklch(...)`; a semantic colour is one value, or `{light, dark}`;
`{primitive.x.y}` and `{color.z}` are aliases. `checks.contrast` lists `[foreground, background, minimum, backdrop]` pairs, both
schemes. `$type` `dimension-theme` and `cubicBezier` are emitted into Tailwind's `@theme`.

```json tokens
{
  "meta": {
    "id": "blue",
    "name": "Blue",
    "version": "1.0.0",
    "note": "A calm blue accent with cool neutrals. In sRGB and AA contrast in both schemes (ADR-0081 DS2)."
  },
  "primitive": {
    "color": {
      "frost": {
        "25": {
          "$type": "color",
          "$value": "oklch(95% 0.006 250)"
        },
        "50": {
          "$type": "color",
          "$value": "oklch(97% 0.004 250)"
        },
        "100": {
          "$type": "color",
          "$value": "oklch(96% 0.006 250)"
        },
        "200": {
          "$type": "color",
          "$value": "oklch(90% 0.01 250)"
        }
      },
      "white": {
        "100": {
          "$type": "color",
          "$value": "oklch(100% 0 0)"
        },
        "99": {
          "$type": "color",
          "$value": "oklch(99% 0 0)"
        }
      },
      "slate": {
        "950": {
          "$type": "color",
          "$value": "oklch(15% 0.012 255)"
        },
        "900": {
          "$type": "color",
          "$value": "oklch(21% 0.02 255)"
        },
        "800": {
          "$type": "color",
          "$value": "oklch(21% 0.014 255)"
        },
        "700": {
          "$type": "color",
          "$value": "oklch(26% 0.016 255)"
        },
        "600": {
          "$type": "color",
          "$value": "oklch(34% 0.018 255)"
        },
        "500": {
          "$type": "color",
          "$value": "oklch(49% 0.02 255)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(70% 0.016 255)"
        }
      },
      "blue": {
        "600": {
          "$type": "color",
          "$value": "oklch(50% 0.17 258)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(76% 0.12 250)"
        },
        "950": {
          "$type": "color",
          "$value": "oklch(19% 0.04 250)"
        }
      },
      "teal": {
        "600": {
          "$type": "color",
          "$value": "oklch(55% 0.09 205)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(78% 0.11 205)"
        }
      },
      "sky": {
        "300": {
          "$type": "color",
          "$value": "oklch(80% 0.11 235)"
        }
      },
      "green": {
        "600": {
          "$type": "color",
          "$value": "oklch(52% 0.125 155)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(76% 0.15 155)"
        },
        "100": {
          "$type": "color",
          "$value": "oklch(95% 0.03 140)"
        },
        "800": {
          "$type": "color",
          "$value": "oklch(28% 0.04 140)"
        },
        "700": {
          "$type": "color",
          "$value": "oklch(42% 0.11 145)"
        },
        "200": {
          "$type": "color",
          "$value": "oklch(82% 0.12 140)"
        }
      },
      "amber": {
        "600": {
          "$type": "color",
          "$value": "oklch(58% 0.12 70)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(82% 0.13 80)"
        }
      },
      "red": {
        "600": {
          "$type": "color",
          "$value": "oklch(55% 0.19 25)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(74% 0.14 25)"
        }
      },
      "scrim": {
        "blue": {
          "$type": "color",
          "$value": "oklch(20% 0.03 255 / 0.84)"
        }
      }
    },
    "shadow": {
      "ink": {
        "$type": "color",
        "$value": "oklch(22% 0.03 255)"
      }
    }
  },
  "semantic": {
    "color": {
      "bg": {
        "$type": "color",
        "css": "--bg",
        "$value": {
          "light": "{primitive.color.frost.50}",
          "dark": "{primitive.color.slate.950}"
        },
        "$description": "Page background"
      },
      "surface": {
        "$type": "color",
        "css": "--surface",
        "$value": {
          "light": "{primitive.color.white.100}",
          "dark": "{primitive.color.slate.800}"
        },
        "$description": "Cards, panels, sidebar"
      },
      "surface-solid": {
        "$type": "color",
        "css": "--surface-solid",
        "$value": {
          "light": "{primitive.color.white.100}",
          "dark": "{primitive.color.slate.800}"
        },
        "$description": "Popovers and menus (always opaque)"
      },
      "surface-2": {
        "$type": "color",
        "css": "--surface-2",
        "$value": {
          "light": "{primitive.color.frost.100}",
          "dark": "{primitive.color.slate.700}"
        },
        "$description": "Quiet fills: secondary buttons, muted areas"
      },
      "text": {
        "$type": "color",
        "css": "--text",
        "$value": {
          "light": "{primitive.color.slate.900}",
          "dark": "{primitive.color.frost.25}"
        },
        "$description": "Body text"
      },
      "muted": {
        "$type": "color",
        "css": "--muted",
        "$value": {
          "light": "{primitive.color.slate.500}",
          "dark": "{primitive.color.slate.300}"
        },
        "$description": "Secondary text and captions"
      },
      "border": {
        "$type": "color",
        "css": "--border",
        "$value": {
          "light": "{primitive.color.frost.200}",
          "dark": "{primitive.color.slate.600}"
        },
        "$description": "Lines, input borders"
      },
      "accent": {
        "$type": "color",
        "css": "--accent",
        "$value": {
          "light": "{primitive.color.blue.600}",
          "dark": "{primitive.color.blue.300}"
        },
        "$description": "Primary actions, links, focus"
      },
      "accent-2": {
        "$type": "color",
        "css": "--accent-2",
        "$value": {
          "light": "{primitive.color.teal.600}",
          "dark": "{primitive.color.teal.300}"
        },
        "$description": "Second brand colour: charts, highlights"
      },
      "accent-3": {
        "$type": "color",
        "css": "--accent-3",
        "$value": "{primitive.color.sky.300}",
        "$description": "Third brand colour: charts, highlights"
      },
      "on-accent": {
        "$type": "color",
        "css": "--on-accent",
        "$value": {
          "light": "{primitive.color.white.99}",
          "dark": "{primitive.color.blue.950}"
        },
        "$description": "Text and icons on the accent colour"
      },
      "accent-soft": {
        "$type": "color",
        "css": "--accent-soft",
        "$value": "color-mix(in oklch, {color.accent} 10%, transparent)",
        "$description": "Tinted fill: hovers, selected rows"
      },
      "ok": {
        "$type": "color",
        "css": "--ok",
        "$value": {
          "light": "{primitive.color.green.600}",
          "dark": "{primitive.color.green.300}"
        },
        "$description": "Success"
      },
      "warn": {
        "$type": "color",
        "css": "--warn",
        "$value": {
          "light": "{primitive.color.amber.600}",
          "dark": "{primitive.color.amber.300}"
        },
        "$description": "Warning"
      },
      "danger": {
        "$type": "color",
        "css": "--danger",
        "$value": {
          "light": "{primitive.color.red.600}",
          "dark": "{primitive.color.red.300}"
        },
        "$description": "Errors and destructive actions"
      },
      "ok-soft": {
        "$type": "color",
        "css": "--ok-soft",
        "$value": {
          "light": "{primitive.color.green.100}",
          "dark": "{primitive.color.green.800}"
        },
        "$description": "Fill behind a success label"
      },
      "on-ok-soft": {
        "$type": "color",
        "css": "--on-ok-soft",
        "$value": {
          "light": "{primitive.color.green.700}",
          "dark": "{primitive.color.green.200}"
        },
        "$description": "Text on the success fill"
      },
      "scrim": {
        "$type": "color",
        "css": "--scrim",
        "$value": "{primitive.color.scrim.blue}",
        "$description": "Translucent fill for labels over pictures"
      },
      "on-scrim": {
        "$type": "color",
        "css": "--on-scrim",
        "$value": "{primitive.color.white.100}",
        "$description": "Text and borders on the scrim"
      }
    },
    "radius": {
      "sm": {
        "$type": "dimension",
        "css": "--radius-sm",
        "$value": "0.5rem",
        "$description": "Small controls"
      },
      "md": {
        "$type": "dimension",
        "css": "--radius",
        "$value": "0.85rem",
        "$description": "Cards, inputs"
      },
      "lg": {
        "$type": "dimension",
        "css": "--radius-lg",
        "$value": "1.15rem",
        "$description": "Large panels"
      },
      "control": {
        "$type": "dimension-theme",
        "css": "--radius-control",
        "$value": "0.65rem",
        "$description": "Back links and small buttons"
      }
    },
    "shadow": {
      "raised": {
        "$type": "shadow",
        "css": "--shadow",
        "$value": "0 1px 2px oklch(22% 0.03 255 / 0.05), 0 12px 30px -16px oklch(30% 0.08 255 / 0.22)",
        "$description": "The raised surface"
      }
    },
    "font": {
      "sans": {
        "$type": "fontFamily",
        "css": "--font",
        "$value": "ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif",
        "$description": "Interface text"
      },
      "serif": {
        "$type": "fontFamily",
        "css": "--font-serif",
        "$value": "ui-serif, \"Iowan Old Style\", \"Palatino Linotype\", Georgia, serif",
        "$description": "Headings and long reading"
      }
    },
    "space": {
      "page": {
        "$type": "dimension",
        "css": "--space",
        "$value": "clamp(1rem, 0.8rem + 1vw, 1.75rem)",
        "$description": "Gap between page sections"
      }
    },
    "type": {
      "step--1": {
        "$type": "dimension-theme",
        "css": "--text-step--1",
        "$value": "clamp(0.8rem, 0.78rem + 0.1vw, 0.875rem)",
        "$description": "Captions, labels"
      },
      "step-0": {
        "$type": "dimension-theme",
        "css": "--text-step-0",
        "$value": "clamp(1rem, 0.96rem + 0.2vw, 1.0625rem)",
        "$description": "Body"
      },
      "step-1": {
        "$type": "dimension-theme",
        "css": "--text-step-1",
        "$value": "clamp(1.2rem, 1.1rem + 0.5vw, 1.4rem)",
        "$description": "Small headings"
      },
      "step-2": {
        "$type": "dimension-theme",
        "css": "--text-step-2",
        "$value": "clamp(1.5rem, 1.3rem + 1vw, 2rem)",
        "$description": "Headings"
      },
      "step-3": {
        "$type": "dimension-theme",
        "css": "--text-step-3",
        "$value": "clamp(2.1rem, 1.6rem + 2.5vw, 3.4rem)",
        "$description": "Page titles"
      },
      "2xs": {
        "$type": "dimension-theme",
        "css": "--text-2xs",
        "$value": "0.65rem",
        "$description": "Badges and the smallest labels"
      },
      "ui-sm": {
        "$type": "dimension-theme",
        "css": "--text-ui-sm",
        "$value": "0.8rem",
        "$description": "Dense interface text"
      },
      "ui": {
        "$type": "dimension-theme",
        "css": "--text-ui",
        "$value": "0.9rem",
        "$description": "Interface text"
      },
      "ui-lg": {
        "$type": "dimension-theme",
        "css": "--text-ui-lg",
        "$value": "0.95rem",
        "$description": "Roomy interface text"
      },
      "lead": {
        "$type": "dimension-theme",
        "css": "--text-lead",
        "$value": "1.05rem",
        "$description": "Intro lines"
      },
      "title": {
        "$type": "dimension-theme",
        "css": "--text-title",
        "$value": "1.15rem",
        "$description": "Panel titles"
      },
      "display": {
        "$type": "dimension-theme",
        "css": "--text-display",
        "$value": "clamp(2rem, 8vw, 2.55rem)",
        "$description": "Hero heading, phone"
      },
      "display-lg": {
        "$type": "dimension-theme",
        "css": "--text-display-lg",
        "$value": "clamp(2.55rem, 5.3vw, 3.9rem)",
        "$description": "Hero heading, wide"
      }
    },
    "motion": {
      "ease-soft": {
        "$type": "cubicBezier",
        "css": "--ease-out-soft",
        "$value": "cubic-bezier(0.22, 1, 0.36, 1)",
        "$description": "Entrances and reveals"
      }
    }
  },
  "checks": {
    "contrast": [
      [
        "--text",
        "--bg",
        4.5
      ],
      [
        "--text",
        "--surface",
        4.5
      ],
      [
        "--text",
        "--surface-2",
        4.5
      ],
      [
        "--muted",
        "--bg",
        4.5
      ],
      [
        "--muted",
        "--surface",
        4.5
      ],
      [
        "--muted",
        "--surface-2",
        4.5
      ],
      [
        "--on-accent",
        "--accent",
        4.5
      ],
      [
        "--accent",
        "--bg",
        4.5
      ],
      [
        "--accent",
        "--surface",
        4.5
      ],
      [
        "--text",
        "--accent-soft",
        4.5,
        "--surface"
      ],
      [
        "--accent",
        "--accent-soft",
        4.5,
        "--surface"
      ],
      [
        "--danger",
        "--surface",
        4.5
      ],
      [
        "--ok",
        "--surface",
        4.5
      ],
      [
        "--warn",
        "--surface",
        3.0
      ],
      [
        "--on-ok-soft",
        "--ok-soft",
        4.5
      ],
      [
        "--on-scrim",
        "--scrim",
        4.5,
        "--surface"
      ]
    ]
  }
}
```
