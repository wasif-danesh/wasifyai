# Coding agent: the Browser tab, starting at login and the menu bar

Written 2026-11-15 on the owner's Mac (M5 Pro, macOS 27.0). The Browser tab is a piece of its own by the owner's
choice ("Preview now, Browser after"), built after C6 by the owner's order and stacked on the C6 branch. Starting
at login and the menu bar item were moved here from C6 (ADR-0105, amendment). What is built is described in
`docs/desktop/coding.md`; the decisions are the amendments of 2026-11-15 to ADR-0102 and ADR-0105.

## What was measured

This piece is work in the Tauri shell. The walks drive the window's page in an ordinary browser and cannot
show a second webview, a menu bar item or a closed window. So the shell was given three tests of itself, each
run in the real app (the real shell, the real window, the real engine, on a throwaway data folder).

| Check | Result | How |
|---|---|---|
| A page opens in a second webview inside the real window, and its text comes back | **Passed.** A page served on this computer was opened; "Add this page to the chat" got its title and its 84 characters of text | `WASIFYAI_BROWSER_TEST=http://127.0.0.1:8793/page.html cargo run` |
| The browser goes nowhere but the web | **Passed.** A page that set its own address to `file:///etc/hosts`, `tauri://localhost/index.html` and `http://tauri.localhost/` stayed where it was each time | The same run |
| A page cannot call the shell | **Passed.** A page that asked the shell for the window's token (`engine_session`) was answered "engine_session not allowed" | The same run |
| The browser is removed when it is closed | **Passed** | The same run |
| The switch: on, the window closed, the window back, off | **Passed.** On: the launch agent's file and the menu bar item were there. The window was closed as its red button closes it: it was hidden and the app went on. It was opened again. Off: the file and the item were gone | `WASIFYAI_STAY_TEST=1` with `WASIFYAI_LOGIN_DIR` a throwaway folder |
| A start as at login | **Passed.** With the switch on and `--hidden`: no window shown, the menu bar item there | `WASIFYAI_STAY_TEST=login target/debug/wasifyai-desktop --hidden` |
| The shell's unit tests | **Passed: 44**, 8 of them new (addresses, what is typed, the area, a page's text, the launch agent's file) | `cargo test` |
| The screens | **Passed.** The tab's bar and its words, a page added to the chat, the page taken off the screen under another tab, the switch | `packages/ui/src/code/code.test.tsx` (63 tests), and the walk `ui-audit.sh light code-browser` for two pictures |
| `make test`, `make lint` | **Passed** on the final tree: ruff, the format check, pyright (0 errors), the design check, Biome and the TypeScript check; 3,767 Python tests passed and 498 skipped; 1,317 TypeScript tests (178 client, 220 web, 108 desktop, 811 screens). `make test-coding` was not run again: nothing of the coding engine or the product's Python changed | The full chains |

**No paid run was made.** About 3.75 of the 25 dollars the owner allowed are used, all in stage C3.

## For the owner to look at, in the real window

None of this was seen by a person. These are the things only eyes can judge:

1. **Code › Projects, a session, the Browser tab.** Type an address. The page should sit exactly inside the
   tab's area, below its bar, and follow the window when it is resized.
2. **A dialog over the browser** (the check's dialog, the mode's menu): the page should go away while it is
   open and come back after.
3. **Another tab and back:** the page should be where it was, not loaded again.
4. **"Add this page to the chat":** the page's text appears in the message box.
5. **Code › Scheduled, the switch.** On: an item appears in the menu bar; closing the window leaves the app
   running; "Open Wasify AI" brings it back; "Quit Wasify AI" ends it. macOS will say that a background item
   was added. Off: closing the window quits as before.
6. **Log out and in** with the switch on: Wasify AI should be in the menu bar with no window.

## Found on the way

1. **A menu bar item must be made on the main thread.** Made from another thread the app stopped at once with
   no message. The switch's command is one that runs on the main thread; the shell's test does the same.
2. **On some systems the app's own page is at `http://tauri.localhost`**, an ordinary web address. A browser
   that opened it would be showing the app to itself, with the app's rights. No name under `.localhost` is
   opened.
3. **Tauri answers a web page's call with "not allowed"** when the webview is in no capability: this is what
   keeps a page from the shell, and it is tested in the real app, not assumed.
4. **Starting at login needed no plugin** (ADR-0105 expected one): a launch agent is one small file.
5. **The menu bar item needs system packages on Linux**, so that feature is built for the Mac only. The switch
   is offered on a Mac only anyway.

## Decided while building, for the owner to see

1. **The browser is the person's; the agent gets no browser** (ADR-0102, amendment, point 1).
2. **Searches go to DuckDuckGo.** One line to change.
3. **A page added to the chat is cut at 12,000 characters** and says "its beginning".
4. **The browser keeps its cookies between sessions**, in a store apart from the app's own, so a person stays
   signed in to a site they use.
5. **The switch is off until switched on**, and is one switch for both things, as in the mockup.

## Not measured, not built

- **Nobody looked at the real window** (the list above).
- **A real login.** The start "as at login" was run by hand with `--hidden`.
- **Windows and Linux.** The browser's code is not Mac-only and was not run there; the switch is not offered.
- **A page on the open internet.** The test page was served on this computer.
- Tabs, history, find, downloads and zoom in the browser; a picture of a page for the agent.
