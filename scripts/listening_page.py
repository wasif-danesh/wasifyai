#!/usr/bin/env python3
"""Build docs/listening/index.html from the sample set's manifest (scripts/listening_samples.py): one page
with a player for every sample, what to listen for, a rating and a note for each, kept in the browser,
and a button that copies the results as text.

    python3 scripts/listening_page.py [--samples docs/listening/samples] [--out docs/listening/index.html]

The page is one file with no network use. Open it from the folder it is in, so the relative links to
`samples/` work."""

import argparse
import html
import json
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECTIONS = {
    "speech": (
        "Speech",
        "Text to speech with each model: built-in voices, a voice made from words, a voice copied from a "
        "recording. Judge naturalness first, then correctness (numbers, names), then consistency.",
    ),
    "transcribe": (
        "Speech to text",
        "The app writes down a recording. Read the text next to the audio: count the wrong words.",
    ),
    "music": (
        "Music and sound effects",
        "Songs, instrumentals, edits and effects. The known weak spot is whether lyrics are sung in the right "
        "order and are understandable: a machine cannot check that, you can.",
    ),
    "tools": (
        "Audio tools",
        "Splitting a song into parts, changing a voice, editing words in speech. Always compare with the source "
        "file shown under the sample.",
    ),
    "lipsync": (
        "Lip sync",
        "A still picture says a sentence. Watch the mouth against the words.",
    ),
    "dub": (
        "Dubbing",
        "An English recording said again in Spanish and in German, in the speaker's own copied voice. If you "
        "speak the language, check the translation; everyone can check the voice, the timing and the endings.",
    ),
    "audiobook": (
        "Audiobook",
        "A short book read as one track. Listen for the pauses and for any change of voice or volume between "
        "pieces.",
    ),
}

RATINGS = [("good", "Good"), ("ok", "Acceptable"), ("poor", "Poor"), ("broken", "Broken")]

CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--mute:#57534e;--line:#d6d3d1;--card:#fff;--accent:#0f766e;--warn:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#161412;--fg:#f5f5f4;--mute:#a8a29e;--line:#44403c;--card:#1f1c1a;--accent:#2dd4bf;--warn:#f59e0b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif}
main{max-width:52rem;margin:0 auto;padding:1.5rem 1rem 5rem}h1{font-size:1.6rem;margin:.2rem 0}
h2{font-size:1.25rem;margin:2.5rem 0 .25rem}.lede,.sec{color:var(--mute);margin:.25rem 0 1rem}
.bar{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:.6rem 0;display:flex;gap:1rem;align-items:center;flex-wrap:wrap;z-index:2}
.bar progress{flex:1;min-width:8rem}.card{background:var(--card);border:1px solid var(--line);border-radius:.8rem;padding:1rem;margin:.9rem 0}
.card h3{font-size:1.05rem;margin:0 0 .4rem}.listen{margin:.4rem 0}.meta{font-size:.85rem;color:var(--mute);margin:.3rem 0}
audio{width:100%;height:2.6rem}video{width:100%;max-height:26rem;border-radius:.5rem;background:#000}
.also{margin:.6rem 0 0;font-size:.9rem}.also span{display:block;color:var(--mute)}
.rate{display:flex;gap:.4rem;flex-wrap:wrap;margin:.7rem 0 .4rem}.rate label{border:1px solid var(--line);border-radius:2rem;padding:.25rem .8rem;cursor:pointer}
.rate input{position:absolute;opacity:0}.rate label:has(input:checked){background:var(--accent);color:#fff;border-color:var(--accent)}
.rate label:has(input:focus-visible){outline:2px solid var(--accent);outline-offset:2px}
textarea{width:100%;min-height:3.2rem;background:transparent;color:inherit;border:1px solid var(--line);border-radius:.5rem;padding:.4rem;font:inherit}
button{font:inherit;border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:.5rem;padding:.4rem .9rem;cursor:pointer}
button.ghost{background:transparent;color:var(--accent)}.text{white-space:pre-wrap;font-size:.9rem;background:rgba(127,127,127,.12);padding:.5rem;border-radius:.4rem;margin:.4rem 0}
.skipped{color:var(--warn);font-size:.9rem}details summary{cursor:pointer;color:var(--mute)}
"""

JS = """
const KEY='wasifyai.listening.v1';let state={};
try{state=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){state={}}
function save(){try{localStorage.setItem(KEY,JSON.stringify(state))}catch(e){}}
function refresh(){const ids=[...document.querySelectorAll('[data-id]')].map(e=>e.dataset.id);
 const done=ids.filter(i=>state[i]&&state[i].r).length;
 document.getElementById('count').textContent=done+' of '+ids.length+' rated';
 document.getElementById('prog').value=done;document.getElementById('prog').max=ids.length}
document.querySelectorAll('[data-id]').forEach(card=>{const id=card.dataset.id;const s=state[id]||{};
 card.querySelectorAll('input[type=radio]').forEach(r=>{r.checked=s.r===r.value;r.addEventListener('change',()=>{state[id]={...(state[id]||{}),r:r.value};save();refresh()})});
 const t=card.querySelector('textarea');t.value=s.n||'';t.addEventListener('input',()=>{state[id]={...(state[id]||{}),n:t.value};save()})});
document.getElementById('copy').addEventListener('click',()=>{
 const rows=[...document.querySelectorAll('[data-id]')].map(c=>{const s=state[c.dataset.id]||{};
  return '- '+c.dataset.id+': '+(s.r||'not rated')+(s.n?' ('+s.n.replace(/\\n/g,' ')+')':'')});
 const text='Listening results '+new Date().toISOString().slice(0,10)+'\\n'+rows.join('\\n');
 navigator.clipboard.writeText(text).then(()=>{document.getElementById('copied').textContent='Copied. Paste it into the chat.'},()=>{document.getElementById('copied').textContent='Could not copy: select the list below.';const o=document.getElementById('out');o.hidden=false;o.textContent=text})});
document.getElementById('clear').addEventListener('click',()=>{if(confirm('Forget every rating and note on this page?')){state={};save();location.reload()}});
refresh();
const media=[...document.querySelectorAll('audio,video')];
function check(){const first=media[0];if(first&&first.readyState===0)document.getElementById('trouble').hidden=false}
media.forEach(m=>m.addEventListener('error',()=>{document.getElementById('trouble').hidden=false;if(!m.nextElementSibling||!m.nextElementSibling.classList.contains('bad')){const n=document.createElement('p');n.className='bad skipped';n.textContent='This file could not be loaded here.';m.after(n)}}));
setTimeout(check,3000);
"""


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def length(samples: Path, file: str, known: float | None = None) -> str:
    """How long a sample is, read from its header, so the page can say so before a player has loaded it."""
    seconds = known
    if file.endswith(".wav"):
        try:
            with wave.open(str(samples / file)) as w:
                seconds = w.getnframes() / w.getframerate()
        except (OSError, wave.Error, EOFError):
            pass
    return f"{seconds:.1f} s" if seconds else ""


def media(file: str, label: str | None = None) -> str:
    tag = "video" if file.endswith(".mp4") else "audio"
    src = f"samples/{esc(file)}"
    return (
        f'<div class="also">{f"<span>{esc(label)}</span>" if label else ""}'
        f'<{tag} controls preload="metadata" src="{src}"></{tag}></div>'
    )


def card(item: dict, samples: Path) -> str:
    bits = []
    if size := length(samples, item["file"], item.get("seconds")):
        bits.append(f"<strong>{size}</strong>")
    if item.get("model"):
        bits.append(f"model: {esc(item['model'])}")
    if item.get("work_s"):
        bits.append(f"took {item['work_s']} s to make")
    extra = ""
    for key, label in (
        ("source", "The source recording"),
        ("reference", "The voice it copies or aims at"),
        ("compare", "The original, to compare with"),
    ):
        if item.get(key):
            extra += media(item[key], label)
    if item.get("expected") and item.get("heard"):
        extra += f'<div class="text">Expected: {esc(item["expected"])}\nThe app wrote: {esc(item["heard"])}</div>'
    elif item.get("expected"):
        extra += f'<div class="text">Should say: {esc(item["expected"])}</div>'
    if item.get("lyrics"):
        extra += f'<details><summary>The lyrics</summary><div class="text">{esc(item["lyrics"])}</div></details>'
    if item.get("script"):
        rows = "\n".join(
            f"{s['start']:.1f}-{s['end']:.1f}  {s['source']}\n            → {s['text']}"
            for s in item["script"]
        )
        extra += f'<details><summary>The script that was spoken</summary><div class="text">{esc(rows)}</div></details>'
    if item.get("description"):
        extra += f'<div class="meta">Asked for: {esc(item["description"])}</div>'
    radios = "".join(
        f'<label><input type="radio" name="r-{esc(item["id"])}" value="{v}"> {t}</label>'
        for v, t in RATINGS
    )
    return (
        f'<article class="card" data-id="{esc(item["id"])}"><h3>{esc(item["title"])}</h3>'
        f'{media(item["file"])}<p class="listen"><strong>Listen for:</strong> {esc(item["listen"])}</p>'
        f'<p class="meta">{" · ".join(bits)}</p>{extra}'
        f'<div class="rate" role="radiogroup" aria-label="Rating for {esc(item["title"])}">{radios}</div>'
        f'<textarea aria-label="Note for {esc(item["title"])}" placeholder="What you heard (optional)"></textarea></article>'
    )


def build(samples: Path) -> str:
    manifest = json.loads((samples / "manifest.json").read_text())
    items = manifest["items"]
    out = []
    for key, (title, intro) in SECTIONS.items():
        mine = [i for i in items if i["section"] == key]
        skipped = manifest.get("skipped", {}).get(key, [])
        if not mine and not skipped:
            continue
        out.append(f'<section><h2>{esc(title)}</h2><p class="sec">{esc(intro)}</p>')
        out += [card(i, samples) for i in mine]
        for why in skipped:
            out.append(f'<p class="skipped">Not made: {esc(why)}</p>')
        out.append("</section>")
    n = len(items)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Listening check</title><style>{CSS}</style></head><body><main>
<h1>Listening check</h1>
<p class="lede">{n} samples made by Wasify AI on this computer ({esc(manifest.get("made", ""))}). Play each one, rate it
(<em>Good</em>: you would use it; <em>Acceptable</em>: usable with a caveat; <em>Poor</em>: you would not;
<em>Broken</em>: wrong or unusable), and add a note when something stands out. Your answers stay in this browser.
Headphones help. See <code>README.md</code> for the full checklist.</p>
<div id="trouble" class="skipped" hidden role="alert"><strong>The sound files are not loading.</strong> You most likely opened
this page in a preview that cannot read the files next to it. Run
<code>python3 -m http.server 8765 -d docs/listening</code> in the repository, then open
<code>http://127.0.0.1:8765</code> in Safari or Chrome.</div>
<div class="bar"><span id="count"></span><progress id="prog" value="0" max="{n}"></progress>
<button id="copy">Copy results</button><button id="clear" class="ghost">Start again</button><span id="copied" role="status"></span></div>
<pre id="out" hidden></pre>
{"".join(out)}
</main><script>{JS}</script></body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--samples", default=str(ROOT / "docs/listening/samples"))
    ap.add_argument("--out", default=str(ROOT / "docs/listening/index.html"))
    args = ap.parse_args()
    page = build(Path(args.samples))
    Path(args.out).write_text(page)
    print(f"wrote {args.out} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
