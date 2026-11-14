---
name: pictures-with-wasify
description: Make a logo, an icon or a picture for the project with Wasify AI's own picture model, and put it in the project. Use when the project needs a real picture and none is there.
license: Apache-2.0
compatibility: Needs a picture model set up in Wasify AI.
triggers:
  - logo
  - picture
  - icon
  - illustration
  - hero image
---

# Pictures with Wasify AI

When the project needs a picture, have Wasify AI make it. Do not draw one yourself as SVG or with
text characters when a real picture is wanted.

1. Decide what the picture is for and where it goes: a logo at the top of a page, a picture for a
   card, an icon. Choose the file's place in the project first (`assets/logo.png`).
2. Write the description for the picture model, not for a person: what is shown, the style, the
   colours, the background. One or two sentences. For a logo say "flat, simple, plain background".
   Do not ask for words or letters inside the picture: picture models write them badly.
3. Run, alone as the whole command:

   `wasify-make picture "<the description>" <path/to/file.png>`

   Add `--size wide` for a banner or `--size tall` for a phone screen. The person is asked first, and
   the picture can take a few minutes.
4. Read what the command says. If it says nothing was made, tell the person why in plain words and
   go on without the picture; do not try the same command again and again.
5. Use the file in the project: an `img` tag with a text for people who cannot see it (`alt`), a
   size that fits, and the path as the project serves it.
6. Say in your final message which picture you asked for and where it is.

A picture is also kept in the person's library in Wasify AI.
