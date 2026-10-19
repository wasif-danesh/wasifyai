# Template: blue

The default look from ADR-0081 stage DS2: a blue accent (`oklch(50% 0.17 258)` light, `oklch(76% 0.12 250)` dark), cool neutrals, teal and sky as the other brand colours.
Only the tokens block is a template; the rules are in `design/DESIGN.md`. Use it with `pnpm design:use blue`.

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
