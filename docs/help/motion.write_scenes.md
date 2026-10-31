---
action: motion.write_scenes
screen: motion
synonyms: [start a promo, make an advert, write a social video, video with scenes, several scenes]
---
# Write a video of several scenes

Action: `motion.write_scenes`

## What it is for

Start a video made of several scenes, one after another: for a product promotion, an advert or a social post. Each scene is a title, a quote, a chart, a name strap or captions, and has its own words, length and look. Nothing is drawn until you make the video. The Motion graphics screen for scenes is being built; for now the assistant and other apps can write and change these projects.

## Steps in the app

1. Ask the assistant for the video you want, or use this action from another app.
2. Check the scenes it wrote.
3. Choose Make the video.

## Fields

- `name`: The project's name.
- `shape`: landscape, portrait or square, for the whole video.
- `font`: sans or serif, for the whole video.
- `scenes`: The scenes in order. Each has a `kind` (title, quote, chart, lower_third or captions), its `fields` and an optional `name`. A scene is 5 seconds unless `seconds` says otherwise.

## Limits

- Up to 30 scenes and 90 seconds in all.
- Your words are shown exactly as given.

## Needs

- Writing a project needs nothing else. Motion graphics must be set up to make the video.

## Examples

- "A 15 second vertical ad for my coffee, three scenes."

## Problems

- A scene or project that does not fit is refused, and the message says what to change. Nothing changes until it is right.
