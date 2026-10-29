# ADR-0089: The Models page is tabs with a table each, on the desktop and the web

- **Status:** Accepted (owner, 2026-10-22: the cards are confusing; "build and implement it for both desktop and web", after
  seeing a mock-up). Built.
- **Date:** 2026-10-22
- **Supersedes:** the Models page part of ADR-0086 (decision on "nine cards"); the picker on each screen is unchanged.
- **Depends on:** ADR-0086 (one simple model picker), ADR-0087 (engine workers; P5 fetching models from the web)

## Context

ADR-0086 made the Models page nine cards, one for each group of models. In use the cards were confusing: each repeats the same
text, a person has to open a card to see what is on the computer, and sizes cannot be compared. The web had no Models
page at all (the menu hid the item), so an admin could not see or get the models of a worker except in a separate Workers table.

## Decision

1. **One tab for each group** (Chat, Images, Video, Voice, Listening, Music, Lip sync, Search, 3D), and under the open tab **a table
   of its models**: name with a plain line about it (and "Recommended" where we have a clear choice), size, state, and one action: **Use**, **Get** (after the dialog that says what is downloaded) or
   **Remove** (after asking). The model in use is first, then what is here, then the recommended, then the rest.
2. **One component for both apps** (`ModelsHome` in `packages/ui`), over the same `ChoicesApi` the pickers use. A group the app
   has no picker for has no tab, so the web shows Voice, Listening, Music and Lip sync (what the workers serve) and the desktop
   shows all nine.
3. **On the web it is the admin's page.** `place="service"` changes the words ("On the worker", "Get on the worker"), and the
   menu shows Models to admins (it opens Admin > Models and workers, under the list of workers). Getting a model is the P5 admin
   job; Remove is not on the web yet (a worker has no remove job). Other people choose a model with the pickers on their screens.
4. **No "Add your own" tab.** What only an expert needs (model folders, files other tools left, the Hugging Face search) stays on
   the desktop under a closed **Advanced** section below the table, as before; it is not a tab and the web has none of it.
5. **Keyboard and screen readers:** a tab list with arrow keys; each action has the model's name in its label.

## Consequences

- One page to learn and one component to test; the web and the desktop cannot drift on it.
- A newcomer sees a table, not a friendly card: the picker on each screen stays the place most people choose, and the first-run
  card for chat is unchanged.
- Nine tabs scroll sideways on a phone.
- The tests and any screenshots of the cards are replaced.
- Not checked: the page rendered in the real Tauri window and in a signed-in web session (the component is tested in jsdom).
