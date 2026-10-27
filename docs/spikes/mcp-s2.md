# Spike S2: a file in, a file out, without an arbitrary-path hole (2026-10-27)

`docs/phase4-agent-plan.md` spike S2, for ADR-0069 decision 6. The question: how does an agent hand the app a file
(a recording to transcribe) and get one back (an export) when the path comes from a program that reads untrusted
text? The answer is a small module with the rules, and a test of 26 hostile paths.

## What was built

`wasifyai_platform_sdk.folders`: `AllowedFolders(read, write)` and `resolve(path, mode)`, which answers the real place
a path points at or raises `PathRefused(code, message)` with the rule that failed, as a sentence a client can act on.
The rules, in the order they are checked:

1. The path is a string, at most 4,096 characters, with no NUL byte, line break or backslash; not a `file:` address;
   absolute (`~` and relative paths are refused: the app does not guess whose home or which folder).
2. No `..` segment, even one that would stay inside the folder (`Documents/sub/../note.txt`): no guessing.
3. Symbolic links are followed (`Path.resolve`), and the place the path really points at must be inside one of the
   connection's folders, which are resolved the same way. A folder that is itself a link works; a link inside the
   folder that points outside does not; a prefix (`Documents2`) is not inside `Documents`.
4. A read needs a regular file that exists (a folder, a pipe or a device is refused).
5. A write refuses a path that is a link, needs a parent folder that exists inside a **write** folder (read folders
   are read only), and refuses a target that exists and is not a regular file. Overwriting a regular file is allowed:
   the action that writes (an export) decides whether to ask.

Another spelling of the folder's case (`/users/me/documents`) is refused, not matched: on a case-insensitive file
system that is conservative, never wrong.

## The 26 hostile paths (`packages/platform-sdk/tests/test_folders.py`)

| Path sent | Mode | Refused as |
|---|---|---|
| `note.txt`, `~/Documents/note.txt`, `file:///…` | read | `not_absolute` |
| empty, blank | read | `no_path` |
| `Documents/../../etc/passwd`, `Documents/sub/../note.txt`, `Documents/..` | read, write | `dotdot` |
| a NUL byte, a line break, backslashes (`Documents\..\..\etc\passwd`) | read | `bad_characters` |
| `/etc/passwd`; `Documents2/x.txt` (a prefix); `Documents/out.txt` (a link to `/etc/passwd`); `Documents/outdir/passwd` (through a linked folder); the same for a write; a write into a read-only folder; a write into the folder's parent; `/` | read, write | `outside` |
| a file that is not there | read | `missing` |
| a folder, a named pipe | read, write | `not_a_file` |
| a write under a folder that does not exist | write | `no_folder` |
| a write through a link | write | `link` |
| a path of 5,000 characters; not a string | read | `too_long`, `no_path` |

Eight honest paths pass, among them a link that stays inside the folder, the folder reached by another name (a link
to it), a file to create, and a file to overwrite.

## macOS permissions (Documents, Desktop, Downloads)

Not measured in this spike. What applies: the engine is a child of the app bundle, and macOS attributes a child
process's file access to the responsible app, so the first read of `~/Documents` by the engine raises the app's own
"Wasify AI would like to access files in your Documents folder" prompt, once. A connection's folders should therefore
default to a folder the app owns (`~/Documents/Wasify AI exports`, created by the app) so the prompt is shown when
the person adds a folder in Settings, not in the middle of an agent's call. To be checked in M2 when `library_export`
exists: the prompt, a denied prompt (the read fails with EPERM, which `resolve` reports as `missing`), and the
notarised build.

## What this decides for M1 and M2

- The rules live in the SDK, not in the MCP server, so API keys (K1) and the agent (G1) reuse them.
- Every path a client sends goes through `resolve` before the executor sees it; the action's own input model carries
  the path as a string, and the MCP layer resolves it against the connection's folders.
- The default folders of a new connection: read none, write `~/Documents/Wasify AI exports` (ADR-0069 decision 6).
