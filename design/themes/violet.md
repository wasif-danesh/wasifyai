# Template: violet

The look the app had before the move to blue (ADR-0081). Only the tokens block is a template; the rules are in `design/DESIGN.md`.
Use it with `pnpm design:use violet`.

```json tokens
{
  "meta": {
    "id": "violet",
    "name": "Violet",
    "version": "1.0.0",
    "note": "The look before ADR-0081 stage DS2: violet accent, warm neutrals."
  },
  "primitive": {
    "color": {
      "sand": {
        "25": {
          "$type": "color",
          "$value": "oklch(95% 0.004 90)"
        },
        "50": {
          "$type": "color",
          "$value": "oklch(96.8% 0.006 90)"
        },
        "100": {
          "$type": "color",
          "$value": "oklch(97% 0.004 90)"
        },
        "200": {
          "$type": "color",
          "$value": "oklch(90% 0.004 90)"
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
      "ink": {
        "950": {
          "$type": "color",
          "$value": "oklch(14.5% 0.004 260)"
        },
        "900": {
          "$type": "color",
          "$value": "oklch(21% 0.006 260)"
        },
        "800": {
          "$type": "color",
          "$value": "oklch(22% 0.004 260)"
        },
        "700": {
          "$type": "color",
          "$value": "oklch(26% 0.005 260)"
        },
        "600": {
          "$type": "color",
          "$value": "oklch(34% 0.005 260)"
        },
        "500": {
          "$type": "color",
          "$value": "oklch(49% 0.006 260)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(69% 0.006 260)"
        }
      },
      "violet": {
        "600": {
          "$type": "color",
          "$value": "oklch(47% 0.2 286)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(77% 0.14 285)"
        },
        "950": {
          "$type": "color",
          "$value": "oklch(19% 0.04 285)"
        }
      },
      "blue": {
        "600": {
          "$type": "color",
          "$value": "oklch(55% 0.13 260)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(76% 0.12 260)"
        }
      },
      "lime": {
        "300": {
          "$type": "color",
          "$value": "oklch(82% 0.16 135)"
        }
      },
      "green": {
        "600": {
          "$type": "color",
          "$value": "oklch(52% 0.15 155)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(76% 0.17 155)"
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
          "$value": "oklch(58% 0.15 70)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(82% 0.15 80)"
        }
      },
      "red": {
        "600": {
          "$type": "color",
          "$value": "oklch(55% 0.21 25)"
        },
        "300": {
          "$type": "color",
          "$value": "oklch(74% 0.17 25)"
        }
      },
      "scrim": {
        "violet": {
          "$type": "color",
          "$value": "oklch(20% 0.02 280 / 0.72)"
        }
      }
    },
    "shadow": {
      "ink": {
        "$type": "color",
        "$value": "oklch(20% 0.01 260)"
      }
    }
  },
  "semantic": {
    "color": {
      "bg": {
        "$type": "color",
        "css": "--bg",
        "$value": {
          "light": "{primitive.color.sand.50}",
          "dark": "{primitive.color.ink.950}"
        },
        "$description": "Page background"
      },
      "surface": {
        "$type": "color",
        "css": "--surface",
        "$value": {
          "light": "{primitive.color.white.100}",
          "dark": "{primitive.color.ink.800}"
        },
        "$description": "Cards, panels, sidebar"
      },
      "surface-solid": {
        "$type": "color",
        "css": "--surface-solid",
        "$value": {
          "light": "{primitive.color.white.100}",
          "dark": "{primitive.color.ink.800}"
        },
        "$description": "Popovers and menus (always opaque)"
      },
      "surface-2": {
        "$type": "color",
        "css": "--surface-2",
        "$value": {
          "light": "{primitive.color.sand.100}",
          "dark": "{primitive.color.ink.700}"
        },
        "$description": "Quiet fills: secondary buttons, muted areas"
      },
      "text": {
        "$type": "color",
        "css": "--text",
        "$value": {
          "light": "{primitive.color.ink.900}",
          "dark": "{primitive.color.sand.25}"
        },
        "$description": "Body text"
      },
      "muted": {
        "$type": "color",
        "css": "--muted",
        "$value": {
          "light": "{primitive.color.ink.500}",
          "dark": "{primitive.color.ink.300}"
        },
        "$description": "Secondary text and captions"
      },
      "border": {
        "$type": "color",
        "css": "--border",
        "$value": {
          "light": "{primitive.color.sand.200}",
          "dark": "{primitive.color.ink.600}"
        },
        "$description": "Lines, input borders"
      },
      "accent": {
        "$type": "color",
        "css": "--accent",
        "$value": {
          "light": "{primitive.color.violet.600}",
          "dark": "{primitive.color.violet.300}"
        },
        "$description": "Primary actions, links, focus"
      },
      "accent-2": {
        "$type": "color",
        "css": "--accent-2",
        "$value": {
          "light": "{primitive.color.blue.600}",
          "dark": "{primitive.color.blue.300}"
        },
        "$description": "Second brand colour: charts, highlights"
      },
      "accent-3": {
        "$type": "color",
        "css": "--accent-3",
        "$value": "{primitive.color.lime.300}",
        "$description": "Third brand colour: charts, highlights"
      },
      "on-accent": {
        "$type": "color",
        "css": "--on-accent",
        "$value": {
          "light": "{primitive.color.white.99}",
          "dark": "{primitive.color.violet.950}"
        },
        "$description": "Text and icons on the accent colour"
      },
      "accent-soft": {
        "$type": "color",
        "css": "--accent-soft",
        "$value": "color-mix(in oklch, {color.accent} 14%, transparent)",
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
        "$value": "{primitive.color.scrim.violet}",
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
        "$value": "0 1px 2px oklch(20% 0.01 260 / 0.04), 0 12px 30px -16px oklch(20% 0.01 260 / 0.16)",
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
        4.0,
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
        3.0,
        "--surface"
      ]
    ],
    "gamut": "warn",
    "note": "Violet is the old look, kept so a swap can be proven. It has four colours slightly outside sRGB one 4.0:1 pair (accent text on a selected row, dark) and the picture label at 3.1:1 (the scrim is only 72% opaque); the blue template has none."
  }
}
```
