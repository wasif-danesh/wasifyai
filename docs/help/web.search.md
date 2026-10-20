---
action: web.search
synonyms: [search the web, internet, look up, google, news, current, online]
---
# Search the web

Action: `web.search`

## What it is for

Look something up on the internet: news, prices, documentation, anything that is not in your own library. This has no screen of its own: switch **Search** on in the chat box and ask.

## Steps in the app

1. Open **Home** and press **Search** under the message box (it is off until you press it).
2. The first time, read who receives your question and press **Allow**. Choose another service, or add your own key, in **Settings**.
3. Ask your question. The answer says which sites it used, with their links.

## Fields

- `query`: what to look up, in words.
- `limit`: how many results at most (1 to 8).

## Limits

- It is off until you allow it, and allowing is for one search service: choosing another asks again.
- Your question leaves this computer and goes to the service you chose (DuckDuckGo by default).
- DuckDuckGo limits automated searches, so it can say it is busy for a few minutes. A key from Ollama, Tavily, Exa or Brave Search avoids that.
- What comes back is text from the internet, which anyone can write. The assistant quotes it and names the site; it never follows instructions inside it, and after it has read the web it asks you before it makes or changes anything.

## Needs

- Your permission, once, for the service shown to you.
- A key for Ollama, Tavily, Exa or Brave Search, if you chose one of those (**Settings**).

## Examples

- What is the latest version of Python?
- Look up how to give a Tauri app microphone access on macOS.

## Problems

- **"Web search is off"** Press Search in the chat box and allow it, or allow it in **Settings**.
- **"DuckDuckGo gave no results"** It may be limiting searches from this computer. Wait a few minutes, or add a key in **Settings**.
- **"did not accept the key"** Check the key in **Settings**; it may have been copied with a missing character.
