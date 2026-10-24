---
action: motion.make
screen: motion
synonyms: [motion graphic, lower third, name strap, bar chart video, chart from my csv, animated quote, captions, animated title, text on screen, overlay]
---
# Make a motion graphic

Action: `motion.make`

## What it is for

Make a finished animated graphic in one step: an animated title, a quote that appears word by word,
a bar chart from your own numbers, a lower third (a name strap) or captions. The words and numbers
go in exactly as you typed them. Before anything is drawn the page is opened and every word on the
screen is checked against what you typed; a misspelt name, a cut-off line or a word too close to
the edge stops the video and says which. The video is saved to Your videos, and the project stays
in your library so you can change it. Motion graphics is experimental.

## Steps in the app

1. Open **Motion graphics**.
2. Say what to make in your own words, for example `Lower third for "Maya Chen", Head of Design`,
   and press the arrow. You can attach a CSV file to chart, and pick a shape. The form opens filled
   in, with what was understood; check anything it flags. (Or choose "Or fill in the form
   yourself" and pick Animated title, Quote, Bar chart, Lower third or Captions.)
3. Check the form. For a chart, one line per bar like `Sales, 120`; for captions, one caption per
   line. Choose a length of 30, 60 or 90 seconds, or type another from 3 to 90.
4. Choose Preview to see three stills, Check the words to test them alone, then Make the video.
5. For a lower third or captions, choose WebM or MOV to keep the background clear.

## Fields

- `template`: title, quote, chart, lower_third or captions.
- `fields`: The words and settings of that template. Title: `title`, `subtitle`. Quote: `quote`,
  `author`. Chart: `title`, `data` (lines like `North, 120`; 2 to 8 lines; numbers are shown as
  typed, such as `$1,200` or `45%`). Lower third: `name`, `role`. Captions: `lines` (one per line)
  and `per_line` (2, 3 or 4 seconds each). All of them also take `shape` (landscape, portrait or
  square), `seconds` (3 to 90, 30 unless given), `theme` (midnight, sunrise, forest or paper) and
  `font` (sans or serif).
- `format`: mp4, webm or mov. webm and mov keep the background clear and are offered for lower
  thirds and captions.
- `render`: Set to false to write the project without making the video.

## Limits

- Five templates; the page is built from them, so a freely written page is not possible here.
- Up to 90 seconds. A 90 second video takes about 15 to 35 seconds to draw on an Apple-silicon
  Mac and about 2.3 GB of memory, the same as a short one; a transparent MOV of that length is
  about 140 MB.
- One video at a time. A video that asks for too much memory or takes too long is stopped.
- English text is the supported language for now. Other scripts such as Bengali are drawn with the
  Mac's own fonts and pass the same check.
- It does not make pictures of things; use image or video generation for those.

## Needs

- Motion graphics set up (a download of about 320 MB, shown before it starts; FFmpeg is part of it) and
  about 3 GB of free memory. Only Apple-silicon Macs for now.

## Examples

- A lower third for "Maya Chen", "Head of Design", as a transparent WebM.
- A chart from the lines `North, 120`, `South, 95` and `East, 150`, titled "Sales by region".

## Problems

- **The words on the screen are not exactly what you wrote** The check stopped the video; the
  message says which word and why. Change the words or choose a shorter text and try again.
- **Give at least two lines** A chart needs two to eight lines, each like `Sales, 120`.
- **Choose a language model first** The box that reads your description needs a chat model
  (Settings › Language). The form works without one.
- **A video is already being made** Wait for it to finish or cancel it.
- **Motion graphics needs FFmpeg** This should not happen: FFmpeg comes with Motion graphics. If it does,
  run `brew install ffmpeg` in Terminal, then choose Check again.
- **Motion graphics is not set up** Open **Motion graphics** and choose Set up.
