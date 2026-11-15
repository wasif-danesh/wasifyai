---
name: explain-in-plain-words
description: Explain a project, a file or an error for someone who is not a developer. Use when the person asks what something is, what it does, or why something went wrong, and wants it in plain words.
license: Apache-2.0
triggers:
  - plain words
  - explain this
  - in simple terms
  - what does this do
---

# Explain in plain words

The person you are answering is not a developer. They want to understand, not to be taught to program.

1. Read what you are asked about before you answer. Never explain from the file names alone.
2. Start with one sentence that says what the thing is for, in words a visitor of the finished site or
   app would use.
3. Then say how it works, in at most five short steps. Name a file only when the person will need to
   find it, and say what it is in the same breath ("`hours.js`, the file that works out today's
   opening hours").
4. Do not use a technical word without saying what it means the first time. Prefer the everyday word:
   "the page" and not "the DOM", "the list of packages it needs" and not "dependencies".
5. For an error, say three things in this order: what stopped working for the person, why, and what
   can be done about it. Quote the line of the error that matters, not the whole trace.
6. End with what the person can do next, as one or two concrete choices.

Do not change any file while explaining unless you are asked to.
