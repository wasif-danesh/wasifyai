---
action: video_builder.create
screen: video.builder
synonyms: [title card, animated title, write a video, video from a template, text on screen, quote, bar chart, lower third, captions]
---
# Write a video project

Action: `video_builder.create`

## What it is for

Start a video from one of five templates: an animated title, a quote, a bar chart from your own
numbers, a lower third (a name strap) or captions. Nothing is made yet; the project is kept in your
library and you make the video from it. Video Builder is experimental.

## Steps in the app

1. Open **Video › Video Builder**.
2. Choose New video, then what to make.
3. Fill in the form: the words, and the shape, length, look and letters.
4. Choose Preview to see three stills, then Make the video.

## Fields

- `template`: title, quote, chart, lower_third or captions.
- `fields`: The words and settings of that template (for a title: `title`, `subtitle`; for a chart:
  `title` and `data`, lines like `North, 120`; see Make a motion graphic for the rest). Every
  template also takes `shape`, `seconds` (3 to 90, 30 unless given), `theme` and `font`. Words are
  shown exactly as typed.

## Limits

- Five templates. A word limit applies to each field and the message names it.
- English text is the supported language for now.

## Needs

- Nothing to write the project. Making the video needs Video Builder to be set up (a download of
  a few hundred megabytes).

## Examples

- A title card that says "Launch day" with the line "Wasify AI is here".
- A bar chart titled "Sales" from the lines `North, 120` and `South, 95`.

## Problems

- **The title is too long** Shorten it to 80 characters or fewer.
- **The length must be between 3 and 90 seconds** Choose a length in that range.
