---
action: web.read
synonyms: [read a page, open a link, website, article, url]
---
# Read a web page

Action: `web.read`

## What it is for

Read the main text of one public web page, so the assistant can answer from it. This has no screen of its own: it is part of **Search** in the chat box.

## Steps in the app

1. Switch **Search** on in the chat box.
2. Ask a question, or paste a link and ask about it.
3. The assistant reads pages that came from its search or that you pasted, and names them in the answer.

## Fields

- `url`: the address of a public web page.

## Limits

- It opens only addresses from a search or that you typed, never an address a page asked for.
- It refuses addresses on this computer or a private network, and anything that is not an ordinary web page.
- Pages that need JavaScript to show, and sites that refuse programs, cannot be read; it says so.
- Long pages are cut to the first 12,000 characters.

## Needs

- Search switched on and allowed (see **Search the web**).

## Examples

- Read this article and give me the three main points: https://example.com/article

## Problems

- **"could not be read"** The page may need JavaScript, or be a list of links. Try another page from the search.
- **"refused"** The site would not show the page to the assistant (for example a login or a paywall).
