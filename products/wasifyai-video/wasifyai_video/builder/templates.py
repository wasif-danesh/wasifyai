"""The templates of Motion graphics: compositions written once by us, filled with the words.

A template is a set of fields (what the person fills in) and a function from the checked fields to
one HTML file. The words go into the page as escaped text, never as markup and never inside the
script, so a title cannot carry a tag or a script into the render. The animation is a paused GSAP
timeline that the renderer seeks frame by frame (HyperFrames' convention); nothing in the page
reads the clock, so two renders of the same slots are the same file. Fonts are the two open fonts
the component ships (Inter and Source Serif 4, SIL OFL-1.1), copied into each project.

Every template also says which words must be on the screen, and when (`expected`): the exact-text
check (ADR-0079 decision 7) opens the page, seeks to those moments and compares what is drawn with
what the person typed. A template marks each such element `data-slot="<name>"`.

Five templates (ADR-0079): an animated title, a quote that appears word by word, a bar chart from
the person's own numbers, a lower third (a name strap, transparent) and typed captions
(transparent).

A project of scenes (ADR-0096, `SCENES`) is a sixth kind of composition: its slots are a document, a
list of scenes where each is one of the five templates, one after another. It is still one page, so
the sandbox, the check, the worker and search treat it like any other composition."""

import html
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

FPS = 30
SAFE = 0.06  # the title-safe margin, as a share of the width

# shape -> (width, height): 1080p, what social channels ask for (ADR-0096 MX7). Everything on a page
# is sized from these, so an older project looks the same, only sharper.
SHAPES: dict[str, tuple[int, int]] = {
    "landscape": (1920, 1080),
    "portrait": (1080, 1920),
    "square": (1080, 1080),
    "feed": (1080, 1350),
}
# theme -> (background from, background to, text, accent). Presets only: no colour is typed in.
THEMES: dict[str, tuple[str, str, str, str]] = {
    "midnight": ("#0b1220", "#1c2b4a", "#f5f7fb", "#4f8cff"),
    "sunrise": ("#2a0f2e", "#7a2f3b", "#fff4e6", "#ffb347"),
    "forest": ("#0d1f16", "#1f4d3a", "#f1faf4", "#5ad19a"),
    "paper": ("#f6f1e7", "#e4dccb", "#1d1b17", "#c2410c"),
    "night": ("#0b1426", "#3c3266", "#f8f8f6", "#8fb4ff"),
    "sage": ("#d8e0c5", "#9bac95", "#27302a", "#2f6650"),
    "pulse": ("#4a2060", "#181820", "#f8f6fb", "#ff7ab6"),
}
# font -> (family, file in vendor/fonts, css stack): files from the component's npm packages.
FONTS: dict[str, tuple[str, str, str]] = {
    "sans": ("Inter", "inter.woff2", "'Inter', -apple-system, 'Helvetica Neue', Arial, sans-serif"),
    "serif": (
        "Source Serif 4", "source-serif-4.woff2",
        "'Source Serif 4', Georgia, 'Times New Roman', serif",
    ),
}  # fmt: skip
FONT_FILES: dict[str, str] = {
    "inter.woff2": "@fontsource-variable/inter/files/inter-latin-wght-normal.woff2",
    "source-serif-4.woff2": (
        "@fontsource-variable/source-serif-4/files/source-serif-4-latin-wght-normal.woff2"
    ),
}
FORMATS = ("mp4", "webm", "mov")
MAX_SECONDS = 90  # the longest video a template makes (measured in docs/spikes/video-builder-v1.md)


class SlotError(ValueError):
    """What the person typed cannot be used; the message says what to change."""


@dataclass(frozen=True)
class Field:
    """One thing the person fills in. The window builds its form from these."""

    id: str
    kind: str  # text | longtext | lines | rows | choice | seconds
    label: str
    required: bool = False
    max_chars: int = 0  # text, longtext; and for lines and rows, each line
    minimum: int = 0  # seconds; lines and rows: at least this many
    maximum: int = 0  # seconds; lines and rows: at most this many
    default: Any = None
    choices: tuple[tuple[str, str], ...] = ()  # (value, label)
    hint: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "label": self.label, "required": self.required,
            "max_chars": self.max_chars, "min": self.minimum, "max": self.maximum,
            "default": self.default, "choices": [{"id": v, "label": n} for v, n in self.choices],
            "hint": self.hint,
        }  # fmt: skip


@dataclass(frozen=True)
class Expect:
    """Words that must be on the screen at one moment: the slot element and what it must say."""

    slot: str
    text: str
    at: float


@dataclass(frozen=True)
class Template:
    id: str
    title: str
    description: str
    fields: tuple[Field, ...]
    build: Callable[[dict[str, Any], "Look"], tuple[str, str, str]]  # css, body, script
    expected: Callable[[dict[str, Any]], list[Expect]]
    hold: Callable[[dict[str, Any]], float]  # a moment when everything is on the screen
    words: Callable[[dict[str, Any]], str]  # what a project is found by and called
    transparent: bool = False
    formats: tuple[str, ...] = ("mp4",)
    derive: Callable[[dict[str, Any]], dict[str, Any]] | None = None  # slots made of other slots
    derived: tuple[str, ...] = ()  # their names: accepted again when checked slots come back
    primary: str | None = None  # the text field that names a project (None: it cannot be renamed)

    def info(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "description": self.description,
            "fields": [f.public() for f in self.fields], "transparent": self.transparent,
            "formats": list(self.formats),
        }  # fmt: skip


@dataclass(frozen=True)
class Look:
    width: int
    height: int
    top: str
    bottom: str
    ink: str
    accent: str
    stack: str
    transparent: bool


# ---- checking the fields -----------------------------------------------------------------------


def _text(value: Any, label: str, limit: int, required: bool) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if any(ord(c) < 32 for c in text):
        raise SlotError(f"The {label} has characters that cannot be shown.")
    if required and not text:
        raise SlotError(f"Write a {label}.")
    if len(text) > limit:
        raise SlotError(f"The {label} is too long: at most {limit} characters.")
    return text


def _lines(value: Any, f: Field) -> list[str]:
    raw = value.split("\n") if isinstance(value, str) else list(value or [])
    out = [_text(x, f.label.lower(), f.max_chars, False) for x in raw]
    out = [x for x in out if x]
    if len(out) < max(1, f.minimum):
        raise SlotError(f"Write at least {max(1, f.minimum)} line for the {f.label.lower()}.")
    if len(out) > f.maximum:
        raise SlotError(f"The {f.label.lower()} can have at most {f.maximum} lines.")
    return out


_NUMBER = re.compile(r"^[^\d+\-.,]*([+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+))\s*[%A-Za-z]{0,4}$")


def parse_number(text: str) -> float | None:
    """The number in a value as typed ("$1,200", "45%", "3.5 m"), or None."""
    m = _NUMBER.match(text.strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _split_row(line: str, n: int) -> tuple[str, str]:
    """A "label, number" line. The number may hold commas ("West, 1,200.5") and a label may too
    ("Smith, John, 120"): the label ends at the first comma after which a number follows."""
    for i, ch in enumerate(line):
        if ch == "," and parse_number(line[i + 1 :]) is not None:
            return line[:i], line[i + 1 :]
    if "," in line:
        tail = line.rsplit(",", 1)[1].strip()
        raise SlotError(f"Line {n}: “{tail}” is not a number (use 0 or more, like 120 or 45%).")
    raise SlotError(f"Line {n} needs a label, a comma and a number, like: Sales, 120")


def _rows(value: Any, f: Field) -> list[dict[str, str]]:
    """Rows of a chart: "label, value" lines (or {label, value} pairs). The value stays as typed."""
    items: list[tuple[str, str]] = []
    if isinstance(value, str):
        for n, line in enumerate(value.splitlines(), 1):
            if not line.strip():
                continue
            items.append(_split_row(line, n))
    else:
        items = [(str(r.get("label", "")), str(r.get("value", ""))) for r in (value or [])]
    out = []
    for n, (label, number) in enumerate(items, 1):
        label = _text(label, "label", f.max_chars, True)
        number = _text(number, "number", 14, True)
        parsed = parse_number(number)
        if parsed is None or parsed < 0:
            raise SlotError(
                f"Line {n}: “{number}” is not a number (use 0 or more, like 120 or 45%)."
            )
        out.append({"label": label, "value": number})
    if len(out) < max(2, f.minimum):
        raise SlotError("Give at least two lines, each like: Sales, 120")
    if len(out) > f.maximum:
        raise SlotError(f"A chart can have at most {f.maximum} lines.")
    if not any((parse_number(r["value"]) or 0) > 0 for r in out):
        raise SlotError("Give at least one number above zero.")
    return out


def _field(f: Field, raw: dict[str, Any]) -> Any:
    value = raw.get(f.id, f.default)
    if f.kind in ("text", "longtext"):
        return _text(value, f.label.lower(), f.max_chars, f.required)
    if f.kind == "lines":
        return _lines(value, f)
    if f.kind == "rows":
        return _rows(value, f)
    if f.kind == "choice":
        value = value if isinstance(value, str) else str(value)
        allowed = [v for v, _ in f.choices]
        if value not in allowed:
            raise SlotError(f"The {f.label.lower()} must be one of: {', '.join(allowed)}.")
        return value
    if f.kind == "seconds":
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise SlotError("The length must be a number of seconds.") from None
        if not f.minimum <= n <= f.maximum:
            raise SlotError(f"The length must be between {f.minimum} and {f.maximum} seconds.")
        return n
    raise SlotError("That field cannot be used.")


def normalize_slots(template: str, raw: dict[str, Any]) -> dict[str, Any]:
    """The slots of a template, checked and completed. Unknown names are refused, not dropped."""
    if template == SCENES:
        return _normalize_scenes(raw)
    t = TEMPLATES.get(template)
    if t is None:
        raise SlotError("That template does not exist.")
    known = {f.id for f in t.fields} | set(t.derived)
    extra = sorted(set(raw) - known)
    if extra:
        raise SlotError(f"This template has no setting called {extra[0]}.")
    slots = {f.id: _field(f, raw) for f in t.fields}
    if t.derive:
        slots.update(t.derive(slots))
    return slots


def get(template: str) -> Template:
    t = SCENES_TEMPLATE if template == SCENES else TEMPLATES.get(template)
    if t is None:
        raise SlotError("That template does not exist.")
    return t


def describe(template: str, slots: dict[str, Any]) -> str:
    """The words a project is found by and called."""
    return get(template).words(slots)


def title_of(template: str, slots: dict[str, Any]) -> str:
    """A short name for the project list."""
    words = describe(template, slots).split(". ")[0]
    return words if len(words) <= 60 else words[:57].rstrip() + "..."


def preview_times(template: str, slots: dict[str, Any]) -> list[float]:
    """Three moments for the preview: coming in, half way, and everything on the screen. For
    several scenes, the moment everything is on the screen in each of the first three."""
    if template == SCENES and len(slots["scenes"]) > 1:
        starts = scene_starts(slots)
        return [
            round(start + TEMPLATES[scene["kind"]].hold(scene_slots(slots, scene)), 2)
            for scene, start in zip(slots["scenes"][:3], starts, strict=False)
        ]
    if template == SCENES:
        scene = slots["scenes"][0]
        return preview_times(scene["kind"], scene_slots(slots, scene))
    t = get(template)
    hold = t.hold(slots)
    return [round(min(0.6, hold / 2), 2), round(hold / 2, 2), round(hold, 2)]


def expected(template: str, slots: dict[str, Any]) -> list[Expect]:
    return get(template).expected(slots)


# ---- the page ------------------------------------------------------------------------------------


def _look(template: Template, slots: dict[str, Any], brand: dict[str, Any] | None = None) -> Look:
    width, height = SHAPES[slots["shape"]]
    top, bottom, ink, accent = (
        (brand["background"], brand["second"], brand["text"], brand["accent"])
        if brand
        else THEMES[slots["theme"]]
    )
    return Look(
        width, height, top, bottom, ink, accent, FONTS[slots["font"]][2], template.transparent
    )


def render_html(template: str, slots: dict[str, Any]) -> str:
    """The composition's index.html for these slots (checked again here)."""
    if template == SCENES:
        return _render_scenes(normalize_slots(SCENES, slots))
    t = get(template)
    s = normalize_slots(template, slots)
    look = _look(t, s)
    css, body, script = t.build(s, look)
    seconds = s["seconds"]
    family, file, _ = FONTS[s["font"]]
    background = (
        "transparent" if look.transparent else f"linear-gradient(135deg, {look.top}, {look.bottom})"
    )
    page_background = "transparent" if look.transparent else look.top
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width={look.width}, height={look.height}">
<script src="vendor/gsap.min.js"></script>
<style>
  @font-face {{ font-family: "{family}"; font-style: normal; font-weight: 100 900;
    font-display: block; src: url("vendor/fonts/{file}") format("woff2"); }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  [data-slot] {{ overflow-wrap: anywhere; }}
  html, body {{ width: {look.width}px; height: {look.height}px; overflow: hidden;
    background: {page_background}; }}
  #root {{ position: relative; width: {look.width}px; height: {look.height}px; overflow: hidden;
    background: {background}; color: {look.ink}; font-family: {look.stack}; }}
{css}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{seconds}"
     data-width="{look.width}" data-height="{look.height}">
{body}
</div>
<script>
  const tl = gsap.timeline({{ paused: true }});
{script}
  tl.to({{}}, {{ duration: 0.01 }}, {seconds} - 0.01);
  window.__timelines = window.__timelines || {{}};
  window.__timelines["main"] = tl;
  tl.seek(0);
</script>
</body></html>
"""


def _clip(seconds: int) -> str:
    return f'class="clip" data-start="0" data-duration="{seconds}" data-track-index="0"'


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _common_fields(seconds: tuple[int, int, int], font: str = "sans") -> tuple[Field, ...]:
    low, high, default = seconds
    return (
        Field("shape", "choice", "Shape", default="landscape", choices=(
            ("landscape", "Landscape"), ("portrait", "Portrait"), ("square", "Square"),
            ("feed", "Feed (4:5)"),)),
        Field("seconds", "seconds", "Length", minimum=low, maximum=high, default=default),
        Field("theme", "choice", "Look", default="midnight", choices=tuple(
            (k, k.title()) for k in THEMES)),
        Field("font", "choice", "Letters", default=font, choices=(
            ("sans", "Sans (Inter)"), ("serif", "Serif (Source Serif 4)"))),
    )  # fmt: skip


# ---- 1. animated title --------------------------------------------------------------------------


def _shrink(text: str, ok: int, small: int, tiny: int | None = None) -> float:
    """How much to shrink the letters so a long text still fits: 1 up to `ok` characters."""
    n = len(text)
    if n <= ok:
        return 1.0
    if n <= small:
        return 0.8
    return 0.65 if tiny is None or n <= tiny else 0.5


def _title_build(s: dict[str, Any], look: Look) -> tuple[str, str, str]:
    w, h = look.width, look.height
    big = round(min(w, h) * (0.105 if w >= h else 0.12) * _shrink(s["title"], 24, 40, 60))
    small = round(min(w, h) * (0.105 if w >= h else 0.12) * 0.38 * _shrink(s["subtitle"], 60, 100))
    css = f"""  #stage {{ position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: {round(big * 0.28)}px;
    padding: {round(w * 0.08)}px; text-align: center; }}
  .bar {{ width: {round(min(w, h) * 0.16)}px; height: {max(6, round(big * 0.07))}px;
    background: {look.accent}; border-radius: 999px; transform-origin: left center; }}
  .mask {{ overflow: hidden; padding: 0.35em 0 0.55em; }}
  .title {{ font-size: {big}px; font-weight: 700; line-height: 1.15; letter-spacing: -0.02em;
    text-wrap: balance; }}
  .sub {{ font-size: {small}px; font-weight: 400; line-height: 1.35; opacity: 0.82;
    max-width: {round(w * 0.78)}px; text-wrap: balance; }}"""
    sub = f'<p id="sub" data-slot="subtitle" class="sub">{_e(s["subtitle"])}</p>'
    body = f"""  <div id="stage" {_clip(s["seconds"])}>
    <div id="bar" class="bar"></div>
    <div class="mask"><h1 id="title" data-slot="title" class="title">{_e(s["title"])}</h1></div>
    {sub if s["subtitle"] else ""}
  </div>"""
    script = """  tl.from("#bar", { scaleX: 0, duration: 0.7, ease: "power3.out" }, 0.15);
  tl.from("#title", { yPercent: 120, duration: 0.9, ease: "expo.out" }, 0.35);
  if (document.getElementById("sub")) {
    tl.from("#sub", { y: 24, opacity: 0, duration: 0.8, ease: "power2.out" }, 0.85);
  }"""
    return css, body, script


def _title_expected(s: dict[str, Any]) -> list[Expect]:
    at = _title_hold(s)
    out = [Expect("title", s["title"], at)]
    return out + ([Expect("subtitle", s["subtitle"], at)] if s["subtitle"] else [])


def _title_hold(s: dict[str, Any]) -> float:
    return round(s["seconds"] - 0.1, 2)


# ---- 2. quote, word by word ----------------------------------------------------------------------


def _quote_build(s: dict[str, Any], look: Look) -> tuple[str, str, str]:
    w, h = look.width, look.height
    words = len(s["quote"].split())
    size = round(min(w, h) * (0.075 if words <= 14 else 0.06 if words <= 28 else 0.048))
    css = f"""  #stage {{ position: absolute; inset: 0; display: flex; flex-direction: column;
    justify-content: center; gap: {round(size * 0.7)}px; padding: {round(w * 0.1)}px; }}
  .mark {{ font-size: {round(size * 2.2)}px; line-height: 0.6; color: {look.accent};
    font-weight: 700; height: {round(size * 0.9)}px; }}
  .quote {{ font-size: {size}px; font-weight: 600; line-height: 1.25; letter-spacing: -0.01em;
    max-width: {round(w * 0.8)}px; }}
  .quote .w {{ display: inline-block; }}
  .by {{ font-size: {round(size * 0.5)}px; opacity: 0.8; display: flex; align-items: center;
    gap: {round(size * 0.35)}px; }}
  .by::before {{ content: ""; width: {round(size * 0.9)}px; height: 3px; background: {look.accent};
    border-radius: 999px; }}"""
    by = f'<p id="by" data-slot="author" class="by">{_e(s["author"])}</p>' if s["author"] else ""
    body = f"""  <div id="stage" {_clip(s["seconds"])}>
    <div class="mark" aria-hidden="true">&#8220;</div>
    <p id="quote" data-slot="quote" class="quote">{_e(s["quote"])}</p>
    {by}
  </div>"""
    script = f"""  const quote = document.getElementById("quote");
  const spoken = quote.textContent.split(" ");
  quote.textContent = "";
  spoken.forEach((word, i) => {{
    const span = document.createElement("span");
    span.className = "w";
    span.textContent = word;
    quote.appendChild(span);
    if (i < spoken.length - 1) quote.appendChild(document.createTextNode(" "));
  }});
  const step = Math.min(0.09, {s["seconds"] * 0.5} / spoken.length);
  tl.from(".mark", {{ opacity: 0, y: 20, duration: 0.6, ease: "power2.out" }}, 0.1);
  tl.from(".quote .w", {{ opacity: 0, y: 22, duration: 0.55, ease: "power3.out",
    stagger: step }}, 0.35);
  if (document.getElementById("by")) {{
    tl.from("#by", {{ opacity: 0, x: -18, duration: 0.6, ease: "power2.out" }},
      0.35 + step * spoken.length + 0.4);
  }}"""
    return css, body, script


def _quote_expected(s: dict[str, Any]) -> list[Expect]:
    at = _title_hold(s)
    out = [Expect("quote", s["quote"], at)]
    return out + ([Expect("author", s["author"], at)] if s["author"] else [])


# ---- 3. bar chart --------------------------------------------------------------------------------


def _chart_build(s: dict[str, Any], look: Look) -> tuple[str, str, str]:
    w, h = look.width, look.height
    rows = s["data"]
    top = max(parse_number(r["value"]) or 0 for r in rows)
    big = round(min(w, h) * 0.07)
    size = round(min(w, h) * (0.046 if len(rows) <= 5 else 0.038))
    css = f"""  #stage {{ position: absolute; inset: 0; display: flex; flex-direction: column;
    justify-content: center; gap: {round(big * 0.7)}px;
    padding: {round(h * 0.09)}px {round(w * 0.08)}px; }}
  .title {{ font-size: {big}px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.2;
    overflow: hidden; padding: 0.1em 0 0.35em; }}
  .rows {{ display: grid; gap: {round(size * 0.55)}px; }}
  .row {{ display: grid; grid-template-columns: {round(w * 0.22)}px 1fr {round(w * 0.1)}px;
    align-items: center; gap: {round(size * 0.6)}px; font-size: {size}px; }}
  .label {{ text-align: right; opacity: 0.85; line-height: 1.25; padding: 0.1em 0; }}
  .track {{ height: {round(size * 1.1)}px; background: rgba(127,127,127,0.18);
    border-radius: 999px; overflow: hidden; }}
  .fill {{ height: 100%; background: {look.accent}; border-radius: 999px;
    transform-origin: left center; }}
  .value {{ font-weight: 700; font-variant-numeric: tabular-nums; padding: 0.1em 0; }}"""
    items = []
    for i, r in enumerate(rows):
        share = max(0.02, (parse_number(r["value"]) or 0) / top) if top else 0.02
        items.append(
            f'    <div class="row"><span class="label" data-slot="label-{i}">'
            f"{_e(r['label'])}</span>"
            f'<div class="track"><div class="fill" style="width:{share * 100:.2f}%"></div></div>'
            f'<span class="value" data-slot="value-{i}">{_e(r["value"])}</span></div>'
        )
    body = f"""  <div id="stage" {_clip(s["seconds"])}>
    <h1 class="title" data-slot="title">{_e(s["title"])}</h1>
    <div class="rows">
{chr(10).join(items)}
    </div>
  </div>"""
    script = """  tl.from(".title", { opacity: 0, y: 20, duration: 0.6, ease: "power2.out" }, 0.1);
  tl.from(".label", { opacity: 0, x: -16, duration: 0.5, ease: "power2.out", stagger: 0.12 }, 0.4);
  tl.from(".fill", { scaleX: 0, duration: 0.9, ease: "power3.out", stagger: 0.12 }, 0.5);
  tl.from(".value", { opacity: 0, duration: 0.5, ease: "power1.out", stagger: 0.12 }, 1.1);"""
    return css, body, script


def _chart_expected(s: dict[str, Any]) -> list[Expect]:
    at = _title_hold(s)
    out = [Expect("title", s["title"], at)]
    for i, r in enumerate(s["data"]):
        out += [Expect(f"label-{i}", r["label"], at), Expect(f"value-{i}", r["value"], at)]
    return out


# ---- 4. lower third ------------------------------------------------------------------------------


def _third_build(s: dict[str, Any], look: Look) -> tuple[str, str, str]:
    w, h = look.width, look.height
    big = round(min(w, h) * (0.052 if w >= h else 0.058))
    small = round(big * 0.55)
    panel = "rgba(11,18,32,0.92)" if look.ink != "#1d1b17" else "rgba(246,241,231,0.94)"
    css = f"""  #third {{ position: absolute; left: {round(w * SAFE)}px;
    bottom: {round(h * 0.12)}px;
    display: flex; align-items: stretch; max-width: {round(w * (1 - 2 * SAFE))}px; }}
  .accent {{ width: {max(8, round(big * 0.16))}px; background: {look.accent};
    border-radius: 4px 0 0 4px; }}
  .panel {{ background: {panel}; padding: {round(big * 0.4)}px {round(big * 0.7)}px;
    border-radius: 0 8px 8px 0; display: grid; gap: {round(big * 0.12)}px; }}
  .name {{ font-size: {big}px; font-weight: 700; line-height: 1.15; letter-spacing: -0.01em;
    padding: 0.05em 0; }}
  .role {{ font-size: {small}px; font-weight: 500; line-height: 1.25; opacity: 0.8;
    padding: 0.05em 0; }}"""
    role = f'<div class="role" data-slot="role">{_e(s["role"])}</div>' if s["role"] else ""
    body = f"""  <div id="third" {_clip(s["seconds"])}>
    <div class="accent"></div>
    <div class="panel"><div class="name" data-slot="name">{_e(s["name"])}</div>{role}</div>
  </div>"""
    out_at = s["seconds"] - 0.6
    script = f"""  tl.set("#third", {{ autoAlpha: 1 }}, 0);
  tl.from("#third", {{ x: -60, autoAlpha: 0, duration: 0.6, ease: "power3.out" }}, 0.1);
  tl.to("#third", {{ x: -40, autoAlpha: 0, duration: 0.5, ease: "power2.in" }}, {out_at});"""
    return css, body, script


def _third_hold(s: dict[str, Any]) -> float:
    return round((0.7 + s["seconds"] - 0.6) / 2, 2)


def _third_expected(s: dict[str, Any]) -> list[Expect]:
    at = _third_hold(s)
    out = [Expect("name", s["name"], at)]
    return out + ([Expect("role", s["role"], at)] if s["role"] else [])


# ---- 5. captions ---------------------------------------------------------------------------------


def _captions_derive(s: dict[str, Any]) -> dict[str, Any]:
    seconds = max(2, int(s["per_line"]) * len(s["lines"]))
    if seconds > MAX_SECONDS:
        raise SlotError(
            f"These captions would run {seconds} seconds; the longest is {MAX_SECONDS}. "
            "Use fewer lines or a shorter time for each."
        )
    return {"seconds": seconds}


def _captions_build(s: dict[str, Any], look: Look) -> tuple[str, str, str]:
    w, h = look.width, look.height
    size = round(min(w, h) * (0.052 if w >= h else 0.058))
    per = int(s["per_line"])
    css = f"""  #caps {{ position: absolute; left: {round(w * SAFE)}px; right: {round(w * SAFE)}px;
    bottom: {round(h * 0.1)}px; display: flex; justify-content: center; }}
  .cap {{ position: absolute; bottom: 0; max-width: {round(w * 0.86)}px; text-align: center;
    font-size: {size}px; font-weight: 600; line-height: 1.3; padding: {round(size * 0.3)}px
    {round(size * 0.6)}px; border-radius: 10px; background: rgba(8,12,20,0.78); color: #fff;
    opacity: 0; text-wrap: balance; }}"""
    caps = "\n".join(
        f'    <div class="cap" data-slot="caption-{i}">{_e(line)}</div>'
        for i, line in enumerate(s["lines"])
    )
    body = f"""  <div id="caps" {_clip(s["seconds"])}>
{caps}
  </div>"""
    script = f"""  document.querySelectorAll(".cap").forEach((el, i) => {{
    const at = i * {per};
    tl.to(el, {{ opacity: 1, y: 0, duration: 0.25, ease: "power2.out" }}, at + 0.05);
    tl.to(el, {{ opacity: 0, duration: 0.2, ease: "power1.in" }}, at + {per} - 0.25);
  }});
  gsap.set(".cap", {{ y: 10 }});"""
    return css, body, script


def _captions_expected(s: dict[str, Any]) -> list[Expect]:
    per = int(s["per_line"])
    return [Expect(f"caption-{i}", line, i * per + per / 2) for i, line in enumerate(s["lines"])]


def _captions_hold(s: dict[str, Any]) -> float:
    return round(int(s["per_line"]) / 2, 2)


def _end_build(s: dict[str, Any], look: Look) -> tuple[str, str, str]:
    w, h = look.width, look.height
    big = round(min(w, h) * (0.085 if w >= h else 0.1) * _shrink(s["action"], 24, 40))
    small = round(big * 0.45)
    css = f"""  #stage {{ position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: {round(big * 0.5)}px;
    padding: {round(w * 0.08)}px; text-align: center; }}
  div.end-logo {{ display: none; }}
  img.end-logo {{ max-width: {round(w * 0.4)}px; max-height: {round(h * 0.22)}px; }}
  .action {{ font-size: {big}px; font-weight: 700; line-height: 1.15; letter-spacing: -0.02em;
    color: {look.ink}; text-wrap: balance; }}
  .address {{ font-size: {small}px; font-weight: 500; line-height: 1.35; color: {look.accent}; }}"""
    address = f'<p id="address" data-slot="address" class="address">{_e(s["address"])}</p>'
    body = f"""  <div id="stage" {_clip(s["seconds"])}>
    <div id="logo" class="end-logo"></div>
    <h1 id="action" data-slot="action" class="action">{_e(s["action"])}</h1>
    {address if s["address"] else ""}
  </div>"""
    script = """  if (document.getElementById("logo")) {
    tl.from("#logo", { opacity: 0, scale: 0.9, duration: 0.6, ease: "power2.out" }, 0.1);
  }
  tl.from("#action", { y: 30, opacity: 0, duration: 0.7, ease: "power3.out" }, 0.3);
  if (document.getElementById("address")) {
    tl.from("#address", { opacity: 0, duration: 0.6, ease: "power2.out" }, 0.7);
  }"""
    return css, body, script


def _end_expected(s: dict[str, Any]) -> list[Expect]:
    at = _title_hold(s)
    out = [Expect("action", s["action"], at)]
    return out + ([Expect("address", s["address"], at)] if s["address"] else [])


# ---- the registry -------------------------------------------------------------------------------

TEMPLATES: dict[str, Template] = {
    "title": Template(
        id="title",
        title="Animated title",
        description="A title and a line under it, animated in on a colour you pick.",
        fields=(
            Field("title", "text", "Title", required=True, max_chars=80),
            Field("subtitle", "text", "A line under it", max_chars=140, default=""),
            *_common_fields((3, MAX_SECONDS, 30)),
        ),
        build=_title_build,
        expected=_title_expected,
        hold=_title_hold,
        primary="title",
        words=lambda s: f"{s['title']}. {s['subtitle']}" if s["subtitle"] else s["title"],
    ),
    "quote": Template(
        id="quote",
        title="Quote",
        description="A quote that appears word by word, with who said it.",
        fields=(
            Field("quote", "longtext", "Quote", required=True, max_chars=220),
            Field("author", "text", "Who said it", max_chars=60, default=""),
            *_common_fields((4, MAX_SECONDS, 30), font="serif"),
        ),
        build=_quote_build,
        expected=_quote_expected,
        hold=_title_hold,
        words=lambda s: f"{s['quote']}. {s['author']}" if s["author"] else s["quote"],
    ),
    "chart": Template(
        id="chart",
        title="Bar chart",
        description=(
            "Bars that grow, from your own numbers. Each number is shown exactly as you type it."
        ),
        fields=(
            Field("title", "text", "Title", required=True, max_chars=80),
            Field(
                "data",
                "rows",
                "Numbers",
                required=True,
                max_chars=24,
                minimum=2,
                maximum=8,
                hint="One per line: a label, a comma and a number, like  Sales, 120",
            ),
            *_common_fields((5, MAX_SECONDS, 30)),
        ),
        build=_chart_build,
        expected=_chart_expected,
        hold=_title_hold,
        primary="title",
        words=lambda s: ". ".join([s["title"], *[f"{r['label']} {r['value']}" for r in s["data"]]]),
    ),
    "lower_third": Template(
        id="lower_third",
        title="Lower third",
        description="A name strap for the bottom of a video. Transparent, to lay over footage.",
        fields=(
            Field("name", "text", "Name", required=True, max_chars=60),
            Field("role", "text", "Role", max_chars=80, default=""),
            *_common_fields((3, MAX_SECONDS, 30)),
        ),
        build=_third_build,
        expected=_third_expected,
        hold=_third_hold,
        primary="name",
        transparent=True,
        formats=("webm", "mov", "mp4"),
        words=lambda s: f"{s['name']}. {s['role']}" if s["role"] else s["name"],
    ),
    "end_card": Template(
        id="end_card",
        title="End card",
        description="The last thing people see: your logo, what to do next, and where.",
        fields=(
            Field("action", "text", "What should people do?", required=True, max_chars=60),
            Field("address", "text", "Where? A web address or a place", max_chars=80, default=""),
            *_common_fields((3, MAX_SECONDS, 30)),
        ),
        build=_end_build,
        expected=_end_expected,
        hold=_title_hold,
        primary="action",
        words=lambda s: f"{s['action']}. {s['address']}" if s["address"] else s["action"],
    ),
    "captions": Template(
        id="captions",
        title="Captions",
        description=(
            "Your own words as captions, one after another. Transparent, to lay over footage."
        ),
        fields=(
            Field(
                "lines",
                "lines",
                "Captions",
                required=True,
                max_chars=90,
                minimum=1,
                maximum=45,
                hint="One caption per line",
            ),
            Field(
                "per_line",
                "choice",
                "Seconds each",
                default="3",
                choices=(("2", "2 seconds"), ("3", "3 seconds"), ("4", "4 seconds")),
            ),
            *[f for f in _common_fields((2, MAX_SECONDS, 3)) if f.id != "seconds"],
        ),
        build=_captions_build,
        expected=_captions_expected,
        hold=_captions_hold,
        derive=_captions_derive,
        derived=("seconds",),
        transparent=True,
        formats=("webm", "mov", "mp4"),
        words=lambda s: ". ".join(s["lines"]),
    ),
}
TEMPLATE_ORDER = tuple(TEMPLATES)


# ---- a project of scenes (ADR-0096) --------------------------------------------------------------

SCENES = "scenes"
MAX_SCENES = 30
SCENE_SECONDS = 5  # how long a scene is when no length is given (a template's own default is 30)
_WHOLE_PROJECT = ("shape", "font")  # set once for the project, not per scene
_SCENE_ID = re.compile(r"[0-9a-f]{8}")
TRANSITIONS = ("none", "fade", "slide")  # how a scene starts
_TRANSITION_SECONDS = 0.4
MAX_CAPTION = 140
# the parts of a scene that can be placed on the picture (ADR-0096 MX4): their names, by kind, and
# where each is in the template's markup
CAPTION_PART = ".scene-caption"
PARTS: dict[str, dict[str, str]] = {
    "title": {"bar": ".bar", "title": ".mask", "subtitle": ".sub"},
    "quote": {"mark": ".mark", "quote": ".quote", "author": ".by"},
    "chart": {"title": ".title", "rows": ".rows"},
    "lower_third": {"strap": "#third"},
    "end_card": {"logo": ".end-logo", "action": ".action", "address": ".address"},
    "captions": {"captions": "#caps"},
}
_MIN_WIDTH, _MIN_SCALE, _MAX_SCALE = 3.0, 0.4, 3.0
MAX_ASSETS, MAX_PLACED, MAX_CUES = 60, 6, 60
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_FILE = re.compile(r"[0-9a-f]{8}\.(png|jpg|mp4|mov|webm|m4a|mp3|wav|ogg|flac)")
_PLACED_START = {"x": 35.0, "y": 25.0, "w": 30.0, "scale": 1.0}  # a picture just put on a scene
_PLACED_LEFT, _PLACED_WIDTH = 8.0, 84.0  # a part given only its height on the picture


def scene_slots(document: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    """A scene's fields as the slots its template expects."""
    return {**scene["fields"], "shape": document["shape"], "font": document["font"]}


def scene_starts(document: dict[str, Any]) -> list[int]:
    """When each scene starts in the film, in seconds."""
    starts, at = [], 0
    for scene in document["scenes"]:
        starts.append(at)
        at += scene["fields"]["seconds"]
    return starts


def new_scene_id() -> str:
    return uuid.uuid4().hex[:8]


def parts_of(kind: str, pictures: int = 0) -> dict[str, str]:
    """The parts of a kind of scene that can be placed, its caption, and the pictures put on it."""
    placed = {f"image-{i}": f".placed-{i}" for i in range(pictures)}
    return {**PARTS[kind], "caption": CAPTION_PART, **placed}


def _number(value: Any, low: float, high: float, default: float) -> float:
    try:
        return round(max(low, min(high, float(value))), 3)
    except (TypeError, ValueError):
        return default


def _used(raw: Any, assets: dict[str, dict[str, Any]], kinds: tuple[str, ...]) -> dict | None:
    """A file a scene uses. One that is gone from the project is dropped, not refused: Undo can
    bring back a scene from before a file was removed."""
    if not isinstance(raw, dict):
        return None
    asset = assets.get(str(raw.get("asset")))
    return asset if asset is not None and asset["kind"] in kinds else None


def _background(raw: Any, assets: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    asset = _used(raw, assets, ("image", "video"))
    if asset is None:
        return None
    return {
        "asset": asset["id"],
        "fit": "contain" if raw.get("fit") == "contain" else "cover",
        "x": _number(raw.get("x"), 0, 100, 50),
        "y": _number(raw.get("y"), 0, 100, 50),
        "trim": _number(raw.get("trim"), 0, max(0, asset["seconds"] - 0.1), 0),
        "volume": _number(raw.get("volume"), 0, 1, 0) if asset["has_audio"] else 0,
    }


def _images(raw: Any, assets: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        asset = _used(item, assets, ("image",))
        if asset is not None and len(out) < MAX_PLACED:
            out.append({"asset": asset["id"]})
    return out


def _sound(raw: Any, assets: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    asset = _used(raw, assets, ("audio", "video"))
    if asset is None:
        return None
    return {
        "asset": asset["id"],
        "volume": _number(raw.get("volume"), 0, 1, 0.8),
        "loop": bool(raw.get("loop")),
    }


def _soundtrack(raw: Any, assets: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    found = _sound(raw, assets)
    return {**found, "start": _number(raw.get("start"), 0, MAX_SECONDS, 0)} if found else None


def _cues(raw: Any, seconds: float) -> list[dict[str, Any]]:
    """Captions in time with what is said: lines, each with when it shows, in the scene's own time.
    One that starts after the scene ends is dropped; the words are checked like any others. They
    belong to the scene's sound, and go when it goes: the scene's typed captions show again."""
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        text = _text(item.get("text"), "caption", MAX_CAPTION, False)
        start = _number(item.get("start"), 0, 100_000, 0)
        end = _number(item.get("end"), 0, 100_000, 0)
        if text and start < seconds and end > start:
            out.append({"text": text, "start": start, "end": min(end, float(seconds))})
    return out[:MAX_CUES]


def _normalize_assets(raw: Any) -> list[dict[str, Any]]:
    """The files of a project as the engine wrote them. `file` goes into the page, so it must look
    like what the engine makes; the rest is what the screen shows and the page needs."""
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not _FILE.fullmatch(str(item.get("file"))):
            continue
        if str(item.get("kind")) not in ("image", "video", "audio"):
            continue
        out.append(
            {
                "id": str(item["file"]).split(".")[0],
                "kind": item["kind"],
                "name": _text(item.get("name"), "file name", 120, False) or "My file",
                "file": item["file"],
                "seconds": _number(item.get("seconds"), 0, 100_000, 0),
                "width": int(_number(item.get("width"), 0, 100_000, 0)),
                "height": int(_number(item.get("height"), 0, 100_000, 0)),
                "has_audio": bool(item.get("has_audio")),
                "codec": re.sub(r"[^\w]", "", str(item.get("codec") or ""))[:20],
            }
        )
    return out[:MAX_ASSETS]


def _normalize_arrange(
    kind: str, raw: Any, n: int, pictures: int = 0
) -> dict[str, dict[str, float]]:
    """Where a scene's parts go, as shares of the picture in percent: left, top, width, and how much
    bigger than designed. A part that is not named stays where the template puts it."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SlotError(f"Scene {n}: where its parts go could not be read.")
    known = parts_of(kind, pictures)
    out: dict[str, dict[str, float]] = {}
    # a picture is always placed: it has no place in the design
    with_pictures = {f"image-{i}": _PLACED_START for i in range(pictures)}
    gone = {p for p in raw if p.startswith("image-") and p not in known}
    for part, rect in {**with_pictures, **{k: v for k, v in raw.items() if k not in gone}}.items():
        if part not in known:
            names = ", ".join(known)
            raise SlotError(f"Scene {n} has no part called {part}. It has: {names}.")
        if not isinstance(rect, dict) or set(rect) - {"x", "y", "w", "scale"}:
            raise SlotError(f"Scene {n}: a part is placed with x, y, w and scale.")
        try:
            x = float(rect.get("x", _PLACED_LEFT))
            y = float(rect.get("y", 0))
            w = float(rect.get("w", _PLACED_WIDTH))
            scale = float(rect.get("scale", 1))
        except (TypeError, ValueError):
            raise SlotError(f"Scene {n}: a part is placed with numbers.") from None
        w = max(_MIN_WIDTH, min(100.0, w))
        out[part] = {
            "x": round(max(0.0, min(100.0 - w, x)), 2),
            "y": round(max(0.0, min(100.0, y)), 2),
            "w": round(w, 2),
            "scale": round(max(_MIN_SCALE, min(_MAX_SCALE, scale)), 3),
        }
    return out


def part_selector(scene_id: str, kind: str, part: str, pictures: int = 0) -> str:
    """Where a part is on the page, the same in its rule and for the live preview."""
    found = parts_of(kind, pictures)[part]
    inner = f"#s{scene_id}-{found[1:]}" if found.startswith("#") else found
    return f"#scene-{scene_id} {inner}"


def _arrange_rules(scene: dict[str, Any]) -> str:
    rules = []
    pictures = len(scene.get("images", []))
    for part, r in scene.get("arrange", {}).items():
        rules.append(
            f"  {part_selector(scene['id'], scene['kind'], part, pictures)} {{ position: absolute; "
            f"left: {r['x']}%; top: {r['y']}%; right: auto; bottom: auto; width: {r['w']}%; "
            f"max-width: none; margin: 0; zoom: {r['scale']}; }}"
        )
    return "\n".join(rules)


def live_parts(document: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Every scene's parts and where they are, for the live preview to report and move."""
    return {
        scene["id"]: {
            part: part_selector(scene["id"], scene["kind"], part, len(scene.get("images", [])))
            for part in parts_of(scene["kind"], len(scene.get("images", [])))
        }
        for scene in document["scenes"]
    }


def _normalize_scene(
    raw: Any, n: int, shape: str, font: str, seen: set[str],
    assets: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:  # fmt: skip
    if not isinstance(raw, dict):
        raise SlotError(f"Scene {n} is not a scene.")
    allowed = {
        "id", "name", "kind", "fields", "caption", "transition", "arrange", "background",
        "images", "sound", "cues",
    }  # fmt: skip
    extra = sorted(set(raw) - allowed)
    if extra:
        raise SlotError(f"A scene has no setting called {extra[0]}.")
    kind = raw.get("kind")
    template = TEMPLATES.get(kind) if isinstance(kind, str) else None
    if template is None or not isinstance(kind, str):
        raise SlotError(f"Scene {n} must be one of: {', '.join(TEMPLATE_ORDER)}.")
    fields = dict(raw.get("fields") or {})
    fixed = sorted(set(fields) & set(_WHOLE_PROJECT))
    if fixed:
        raise SlotError(f"The {fixed[0]} is set for the whole project, not for one scene.")
    seconds = next((f for f in template.fields if f.id == "seconds"), None)
    if seconds is not None and "seconds" not in fields:
        fields["seconds"] = max(SCENE_SECONDS, seconds.minimum)
    try:
        slots = normalize_slots(kind, {**fields, "shape": shape, "font": font})
    except SlotError as e:
        raise SlotError(f"Scene {n}: {e}") from None
    given = raw.get("id")
    scene_id = (
        given
        if isinstance(given, str) and _SCENE_ID.fullmatch(given) and given not in seen
        else new_scene_id()
    )
    seen.add(scene_id)
    found = assets or {}
    images = _images(raw.get("images"), found)
    transition = raw.get("transition", "none")
    if transition not in TRANSITIONS:
        raise SlotError(f"Scene {n} must start with one of: {', '.join(TRANSITIONS)}.")
    sound = _sound(raw.get("sound"), found)
    return {
        "id": scene_id,
        "name": _text(raw.get("name"), "scene name", 60, False) or template.title,
        "kind": kind,
        "caption": _text(raw.get("caption"), "caption", MAX_CAPTION, False),
        "transition": transition,
        "arrange": _normalize_arrange(kind, raw.get("arrange"), n, len(images)),
        "background": _background(raw.get("background"), found),
        "images": images,
        "sound": sound,
        "cues": _cues(raw.get("cues"), slots["seconds"]) if sound else [],
        "fields": {k: v for k, v in slots.items() if k not in _WHOLE_PROJECT},
    }


def _brand(raw: Any, assets: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """A brand on a project (`brand.py`): its colours on every scene, and its logo. A colour reaches
    the page's css, so nothing but `#rrggbb` passes."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise SlotError("A brand needs colours.")
    colours = {}
    for name in ("background", "second", "text", "accent"):
        value = raw.get(name)
        if not isinstance(value, str) or not _HEX.fullmatch(value):
            raise SlotError(f"The brand's {name} colour must look like #1a2b3c.")
        colours[name] = value
    logo = assets.get(str(raw.get("logo")))
    return {
        **colours,
        "logo": logo["id"] if logo is not None and logo["kind"] == "image" else None,
        "logo_on_scenes": bool(raw.get("logo_on_scenes", True)),
    }


def plain_text(value: Any, label: str, limit: int) -> str:
    """Words that are not on a scene: checked the same way."""
    return _text(value, label, limit, False)


def _normalize_scenes(raw: dict[str, Any]) -> dict[str, Any]:
    """The document of a project of scenes, checked and completed. Its length comes from its
    scenes. A scene keeps its id; one without an id, or with one already used, gets a new one."""
    extra = sorted(
        set(raw) - {"name", "shape", "font", "scenes", "seconds", "assets", "soundtrack", "brand"}
    )
    if extra:
        raise SlotError(f"A project of scenes has no setting called {extra[0]}.")
    shape, font = raw.get("shape", "landscape"), raw.get("font", "sans")
    if shape not in SHAPES:
        raise SlotError(f"The shape must be one of: {', '.join(SHAPES)}.")
    if font not in FONTS:
        raise SlotError(f"The letters must be one of: {', '.join(FONTS)}.")
    given = raw.get("scenes")
    if not isinstance(given, list) or not given:
        raise SlotError("A project needs at least one scene.")
    if len(given) > MAX_SCENES:
        raise SlotError(f"A project can have at most {MAX_SCENES} scenes.")
    seen: set[str] = set()
    assets = _normalize_assets(raw.get("assets"))
    by_id = {a["id"]: a for a in assets}
    scenes = [_normalize_scene(s, n, shape, font, seen, by_id) for n, s in enumerate(given, 1)]
    seconds = sum(s["fields"]["seconds"] for s in scenes)
    if seconds > MAX_SECONDS:
        raise SlotError(
            f"These scenes would run {seconds} seconds; the longest is {MAX_SECONDS}. "
            "Shorten or remove a scene."
        )
    return {
        "name": _text(raw.get("name"), "project name", 80, False),
        "shape": shape,
        "font": font,
        "seconds": seconds,
        "scenes": scenes,
        "assets": assets,
        "soundtrack": _soundtrack(raw.get("soundtrack"), by_id),
        "brand": _brand(raw.get("brand"), by_id),
    }


def as_scenes(template: str, slots: dict[str, Any]) -> dict[str, Any]:
    """Any project as a document of scenes: a project of one template is one scene."""
    if template == SCENES:
        return slots
    fields = {k: v for k, v in slots.items() if k not in _WHOLE_PROJECT}
    return _normalize_scenes(
        {
            "shape": slots["shape"],
            "font": slots["font"],
            "scenes": [{"kind": template, "fields": fields}],
        }
    )


def _scenes_expected(document: dict[str, Any]) -> list[Expect]:
    out = []
    for scene, start in zip(document["scenes"], scene_starts(document), strict=True):
        template = TEMPLATES[scene["kind"]]
        slots = scene_slots(document, scene)
        for e in template.expected(slots):
            out.append(Expect(f"{scene['id']}-{e.slot}", e.text, round(start + e.at, 2)))
        cues = scene.get("cues") or []
        if scene["caption"] and not cues:
            at = round(start + template.hold(slots), 2)
            out.append(Expect(f"{scene['id']}-caption", scene["caption"], at))
        for i, cue in enumerate(cues):
            at = round(start + (cue["start"] + cue["end"]) / 2, 2)
            out.append(Expect(f"{scene['id']}-cue-{i}", cue["text"], at))
    return out


def _scenes_words(document: dict[str, Any]) -> str:
    said = []
    for scene in document["scenes"]:
        said.append(TEMPLATES[scene["kind"]].words(scene_slots(document, scene)))
        said.append(scene["caption"])
        said.extend(cue["text"] for cue in scene.get("cues") or [])
    return ". ".join(x.rstrip(".") for x in [document["name"], *said] if x)


def poster_time(template: str, slots: dict[str, Any]) -> float:
    """The moment a video's poster shows. A film's first frame can be black (it may fade in), so its
    poster is the first scene with everything on the screen."""
    if template != SCENES:
        return 0
    scene = slots["scenes"][0]
    return TEMPLATES[scene["kind"]].hold(scene_slots(slots, scene))


def is_transparent(template: str, slots: dict[str, Any]) -> bool:
    """Whether the picture has no background. A film is, only if every scene in it is."""
    if template == SCENES:
        return all(
            TEMPLATES[s["kind"]].transparent and not s.get("background") and not s.get("images")
            for s in slots["scenes"]
        ) and not slots.get("brand")
    return get(template).transparent


def formats_of(template: str, slots: dict[str, Any]) -> tuple[str, ...]:
    if template == SCENES:
        kinds = {s["kind"] for s in slots["scenes"]}
        if slots.get("soundtrack") or any(s.get("sound") for s in slots["scenes"]):
            return ("mp4",)
        if is_transparent(template, slots):
            return TEMPLATES[sorted(kinds)[0]].formats
        return ("mp4",)
    return get(template).formats


def _scoped(scene: str, start: int, css: str, body: str, script: str) -> tuple[str, str, str]:
    """One template's css, markup and script, made to live beside other scenes on one page: its ids
    and slots get the scene's prefix, its rules and class selectors reach only inside the scene, and
    its clips start when the scene does. The person's words are escaped (`_e`), so they cannot look
    like the attributes changed here, and no script holds them."""
    root = f"scene-{scene}"
    prefix = f"s{scene}-"  # a selector cannot start with a digit, and an id can
    # a script can name an element that this scene left out (a line under a title, when empty)
    named = {*re.findall(r'\bid="([\w-]+)"', body), *re.findall(r'"#([\w-]+)"', script)}
    ids = sorted(named, key=len, reverse=True)

    def with_ids(text: str) -> str:
        return re.sub(rf"#({'|'.join(ids)})\b", rf"#{prefix}\1", text) if ids else text

    body = re.sub(r'\bid="([\w-]+)"', rf'id="{prefix}\1"', body)
    body = re.sub(r'\bdata-slot="([\w-]+)"', rf'data-slot="{scene}-\1"', body)
    body = body.replace('data-start="0"', f'data-start="{start}"')
    body = body.replace('data-track-index="0"', 'data-track-index="4"')
    script = re.sub(r'getElementById\("([\w-]+)"\)', rf'getElementById("{prefix}\1")', script)
    script = with_ids(script).replace('".', f'"#{root} .')
    return f"  #{root} {{\n{with_ids(css)}\n  }}", body, script


def _cue_times(scene: dict[str, Any]) -> str:
    """Each line of timed captions shows only while it is being said: nothing but numbers and the
    engine's own ids are written into the script."""
    out = []
    for i, cue in enumerate(scene.get("cues") or []):
        sel = f"#s{scene['id']}-cue-{i}"
        out.append(f'    tl.set("{sel}", {{ opacity: 1 }}, {cue["start"]});\n')
        out.append(f'    tl.set("{sel}", {{ opacity: 0 }}, {cue["end"]});\n')
    return "".join(out)


def _transition(kind: str, root: str, height: int) -> str:
    """How a scene comes in: the first thing on its timeline, finished before its words are read."""
    if kind == "fade":
        return (
            f'    tl.from("{root}", {{ opacity: 0, duration: {_TRANSITION_SECONDS}, '
            'ease: "none" }, 0);\n'
        )
    if kind == "slide":
        return (
            f'    tl.from("{root}", {{ opacity: 0, y: {round(height * 0.04)}, '
            f'duration: {_TRANSITION_SECONDS}, ease: "power2.out" }}, 0);\n'
        )
    return ""


def _scene_media(scene: dict[str, Any], start: int, assets: dict[str, dict[str, Any]]) -> str:
    """The scene's background and the pictures on it, under its words. Their files are next to the
    page (`media.py`); `file` was checked when the document was."""
    seconds = scene["fields"]["seconds"]
    timing = f'data-start="{start}" data-duration="{seconds}"'
    sid = f"s{scene['id']}"
    out = []
    back = scene.get("background")
    if back:
        asset = assets[back["asset"]]
        style = f"object-fit: {back['fit']}; object-position: {back['x']}% {back['y']}%;"
        src = f'src="assets/{asset["file"]}"'
        if asset["kind"] == "image":
            out.append(
                f'<img id="{sid}-back" class="clip scene-back" {timing} data-track-index="2" '
                f'{src} style="{style}" alt="">'
            )
        else:
            trim = f' data-media-start="{back["trim"]}"' if back["trim"] else ""
            sound = (
                f' data-has-audio="true" data-volume="{back["volume"]}"'
                if back["volume"] > 0
                else " muted"
            )
            out.append(
                f'<video id="{sid}-back" class="clip scene-back" {timing} data-track-index="2"'
                f'{trim}{sound} {src} style="{style}" playsinline></video>'
            )
    for i, placed in enumerate(scene.get("images", [])):
        asset = assets[placed["asset"]]
        out.append(
            f'<img id="{sid}-placed-{i}" class="clip placed placed-{i}" {timing} '
            f'data-track-index="3" src="assets/{asset["file"]}" alt="">'
        )
    return "\n".join(out)


def _sound_clips(document: dict[str, Any], assets: dict[str, dict[str, Any]]) -> str:
    """The sounds: each scene's during that scene, and the soundtrack from where it starts. A loop
    is the file again, one clip after another, because a clip has one start and one length."""
    out: list[str] = []

    def add(sound: dict[str, Any], start: float, length: float) -> None:
        asset = assets[sound["asset"]]
        each = asset["seconds"] or length
        at = 0.0
        while at < length:
            run = min(each, length - at)
            track = 10 + len(out)
            out.append(
                f'<audio id="sound-{len(out)}" class="clip" data-start="{round(start + at, 3)}" '
                f'data-duration="{round(run, 3)}" data-track-index="{track}" '
                f'data-volume="{sound["volume"]}" src="assets/{asset["file"]}"></audio>'
            )
            at += each
            if not sound["loop"]:
                break

    starts = scene_starts(document)
    for scene, start in zip(document["scenes"], starts, strict=True):
        if scene.get("sound"):
            add(scene["sound"], start, scene["fields"]["seconds"])
    track = document.get("soundtrack")
    if track and track["start"] < document["seconds"]:
        add(track, track["start"], document["seconds"] - track["start"])
    return "\n".join(out)


def _render_scenes(document: dict[str, Any]) -> str:
    width, height = SHAPES[document["shape"]]
    assets = {a["id"]: a for a in document.get("assets", [])}
    family, file, _ = FONTS[document["font"]]
    clear = is_transparent(SCENES, document)
    brand = document.get("brand")
    rules, parts, scripts = [], [], []
    for scene, start in zip(document["scenes"], scene_starts(document), strict=True):
        template = TEMPLATES[scene["kind"]]
        slots = scene_slots(document, scene)
        look = _look(template, slots, brand)
        seconds = slots["seconds"]
        css, body, script = _scoped(scene["id"], start, *template.build(slots, look))
        logo = assets[brand["logo"]] if brand and brand["logo"] else None
        if scene["kind"] == "end_card" and logo:  # its own place, large, instead of in the corner
            body = body.replace(
                f'<div id="s{scene["id"]}-logo" class="end-logo"></div>',
                f'<img id="s{scene["id"]}-logo" class="end-logo" src="assets/{logo["file"]}" '
                'alt="">',
            )
        elif logo and brand["logo_on_scenes"]:
            body = (
                f'<img id="s{scene["id"]}-corner" class="brand-corner" '
                f'src="assets/{logo["file"]}" alt="">\n{body}'
            )
        background = (
            "transparent" if clear else f"linear-gradient(135deg, {look.top}, {look.bottom})"
        )
        rules.append(css)
        placed = _arrange_rules(scene)
        if placed:
            rules.append(placed)
        cues = scene.get("cues") or []
        if cues:
            lines = "".join(
                f'<span id="s{scene["id"]}-cue-{i}" class="cue" data-slot="{scene["id"]}-cue-{i}">'
                f"{_e(cue['text'])}</span>"
                for i, cue in enumerate(cues)
            )
            body += f'\n<div class="scene-caption scene-cues">{lines}</div>'
        elif scene["caption"]:
            body += (
                f'\n<div class="scene-caption"><span data-slot="{scene["id"]}-caption">'
                f"{_e(scene['caption'])}</span></div>"
            )
        parts.append(
            f'<div id="scene-{scene["id"]}" class="clip scene" data-start="{start}" '
            f'data-duration="{seconds}" data-track-index="0" '
            f'style="background: {background}; color: {look.ink}; font-family: {look.stack};">\n'
            f"{_scene_media(scene, start, assets)}\n{body}\n</div>"
        )
        # the film itself shows each scene only in its own time: the renderer hides clips, but the
        # exact-text check opens the page without the renderer's runtime
        root = f"#scene-{scene['id']}"
        hide = f'  gsap.set("{root}", {{ visibility: "hidden" }});\n' if start else ""
        show = f'  film.set("{root}", {{ visibility: "visible" }}, {start});\n' if start else ""
        scripts.append(
            f"""{hide}{show}  film.set("{root}", {{ visibility: "hidden" }}, {start + seconds});
  (() => {{
    const tl = gsap.timeline();
{_transition(scene["transition"], root, height)}{_cue_times(scene)}{script}
    tl.to({{}}, {{ duration: 0.01 }}, {seconds} - 0.01);
    film.add(tl, {start});
  }})();"""
        )
    seconds = document["seconds"]
    newline = chr(10)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width={width}, height={height}">
<script src="vendor/gsap.min.js"></script>
<style>
  @font-face {{ font-family: "{family}"; font-style: normal; font-weight: 100 900;
    font-display: block; src: url("vendor/fonts/{file}") format("woff2"); }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  [data-slot] {{ overflow-wrap: anywhere; }}
  html, body {{ width: {width}px; height: {height}px; overflow: hidden;
    background: {"transparent" if clear else "#000"}; }}
  #root {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; }}
  .scene {{ position: absolute; inset: 0; overflow: hidden; }}
  .scene-back {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
  .placed {{ position: absolute; height: auto; }}
  .brand-corner {{ position: absolute; z-index: 2; top: {round(width * SAFE)}px;
    right: {round(width * SAFE)}px; max-width: {round(min(width, height) * 0.2)}px;
    max-height: {round(min(width, height) * 0.09)}px; }}
  .scene-caption {{ position: absolute; left: 8%; right: 8%;
    bottom: {max(round(height * 0.05), round(width * SAFE + min(width, height) * 0.015))}px;
    text-align: center;
    font-size: {round(min(width, height) * 0.036)}px; line-height: 1.5; color: #fff; }}
  .scene-cues {{ display: grid; }}
  .scene-cues .cue {{ grid-area: 1 / 1; justify-self: center; align-self: end; opacity: 0; }}
  .scene-caption span {{ background: rgba(0,0,0,0.68); padding: 0.25em 0.6em; border-radius: 0.3em;
    -webkit-box-decoration-break: clone; box-decoration-break: clone; }}
{newline.join(rules)}
</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{seconds}"
     data-width="{width}" data-height="{height}">
{newline.join(parts)}
{_sound_clips(document, assets)}
</div>
<script>
  const film = gsap.timeline({{ paused: true }});
{newline.join(scripts)}
  film.to({{}}, {{ duration: 0.01 }}, {seconds} - 0.01);
  window.__timelines = window.__timelines || {{}};
  window.__timelines["main"] = film;
  film.seek(0);
</script>
</body></html>
"""


SCENES_TEMPLATE = Template(
    id=SCENES,
    title="Scenes",
    description="Several scenes, one after another.",
    fields=(),
    build=lambda s, look: ("", "", ""),  # `_render_scenes` makes the page
    expected=_scenes_expected,
    hold=lambda s: float(s["seconds"]),
    words=_scenes_words,
    primary="name",
)


__all__ = [
    "FONT_FILES", "FONTS", "FORMATS", "FPS", "SHAPES", "TEMPLATES", "THEMES", "Expect", "Field",
    "PARTS", "SCENES", "SlotError", "Template", "as_scenes", "describe", "expected", "formats_of",
    "get",
    "is_transparent", "normalize_slots", "parse_number", "preview_times", "render_html",
    "scene_slots", "scene_starts", "title_of",
]  # fmt: skip
