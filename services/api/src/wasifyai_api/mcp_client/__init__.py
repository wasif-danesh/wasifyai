"""The MCP client (ADR-0070, stage C1): the assistant uses other people's MCP servers that the
person added in Settings > Other apps > "Tools from other apps".

    servers.py   a server the person added (transport, address or command, trust, allowed tools),
                 its store and its activity log; the address and command rules (SSRF)
    client.py    one session per server on the SDK's client: the tool list and its cache, a call
                 with its limits (timeout, four in flight, result size), health, the records
    actions.py   `external.call`, the catalogue action the assistant proposes (a card every time)
    routes.py    Settings: add, test, change, remove a server; its tools and activity
"""
