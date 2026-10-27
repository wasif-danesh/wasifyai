---
action: external.call
synonyms: [outside tool, other app, mcp server, connected tool, call a tool]
---
# Use a tool from another app

Action: `external.call`

## What it is for

Run one tool of an outside MCP server you connected under Settings > Other apps > Tools from other apps: a code host, a database, a chat, anything the app itself cannot do. The assistant finds the tool first and shows you a card with the server, the tool and what it would send; nothing leaves this computer until you say so.

## Steps in the app

1. Open Settings > Other apps > Tools from other apps and add the server (its address, or the program that starts it), then Test it to see its tools.
2. In the chat, ask for what the tool does. The assistant proposes the call on a card: check the server, the tool and the arguments, then choose Run.

## Fields

- `connection`: The server's name, as Settings shows it.
- `tool`: The tool's name on that server.
- `arguments`: The tool's arguments, as its input schema says (edit them on the card as JSON).

## Limits

- Every call asks you first; a server set to Blocked is never called.
- A result is cut at 20,000 characters; images and links in it are named, not shown or followed.
- A server that fails three times in a row is left alone until you Test it again.
- A call is given 60 seconds unless the server's timeout says otherwise.

## Needs

- A server added in Settings (desktop only).

## Examples

- Search the issues on github for "crash".
- Ask the database server how many orders came in today.

## Problems

- **There is no server called ...** Check the name under Settings > Other apps > Tools from other apps.
- **... is blocked in Settings** Set its trust to Ask to use it again.
- **... did not answer in 60 seconds** Try again later, or raise the server's timeout in Settings.
