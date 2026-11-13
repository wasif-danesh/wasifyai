---
action: motion.write_scenes
screen: motion
synonyms: [start a promo, make an advert, write a social video, video with scenes, several scenes]
---
# Write a video of several scenes

Action: `motion.write_scenes`

## What it is for

Start a video made of several scenes, one after another: for a product promotion, an advert or a social post. Each scene is a title, a quote, a chart, a name strap or captions, and has its own words, length and look. Nothing is drawn until you make the video. Open it in **Motion graphics** to change it scene by scene.

## Steps in the app

1. Open **Motion graphics** and choose **Video with scenes**, or ask the assistant for the video you want.
2. Write each scene, and see it in the preview.
3. Choose **Make the video**.

## Fields

- `name`: The project's name.
- `shape`: landscape, portrait or square, for the whole video.
- `font`: sans or serif, for the whole video.
- `scenes`: The scenes in order. Each has a `kind` (title, quote, chart, lower_third or captions), its `fields`, and an optional `name`, `caption` and `transition` (none, fade or slide). A scene is 5 seconds unless `seconds` says otherwise.

## Limits

- Up to 30 scenes and 90 seconds in all.
- Your words are shown exactly as given.

## Needs

- Writing a project needs nothing else. Motion graphics must be set up to make the video.

## Examples

- "A 15 second vertical ad for my coffee, three scenes."

## Problems

- A scene or project that does not fit is refused, and the message says what to change. Nothing changes until it is right.
