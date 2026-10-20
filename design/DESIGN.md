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
- Use the product words consistently: *My creations*, *My models*, *Video Builder*, *Motion Graphics*, *Make a 3D model*, *Teach*.
- English only in v1; the layout must still survive longer strings and right-to-left (use logical properties: start and end).

## Components: which to use

| Need | Use |
|---|---|
| The main action | `Button` (filled, accent). One per area. |
| A quieter action | `Button` secondary or outline; destructive uses the `danger` token and confirms in a dialog |
| Pick one of a few | `RadioGroup` or `ToggleGroup`; of many, `Select`; with search, `Command` |
| A setting that applies at once | `Switch` |
| A message about the page | `Notice` (info, warning, error) at the top of the area it concerns; a toast (`Sonner`) only for a result of an action |
| Something takes time | a `ProgressBar` with words (what, how far, how long); the work continues if the person leaves |
| A list of things the person made | cards in a grid with a thumbnail, title and kind filter; the library search is one box |
| Details for experts | a collapsed "For experts" section, closed by default |

Always build from `packages/ui` and `apps/web/components/ui`; do not style a native element by hand.

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

## Screen patterns (written before the screens are built)

- **Chat (the assistant; built on assistant-ui, ADR-0082, `packages/ui/src/chat/thread/`; behind Labs until it passes the parity
  checklist):** a title bar (name, rename, delete) only for a saved chat; while empty, the greeting, the box and three
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
  Everything is a token; at 320 px nothing scrolls sideways (a wide table, code block or diagram scrolls inside its own frame).
- **Teach (training):** a front door with three cards; three steps (add examples, check, train) then "use it"; the app picks the
  settings and shows "Quick" or "Better" and a time (ADR-0073).
- **Agent:** a goal box, starting points, a live feed, approvals as inline cards, Stop always visible, the result saved as a report.
- **Video Builder and Motion Graphics:** describe, preview three stills, change it in words, render; the code view is closed.
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
