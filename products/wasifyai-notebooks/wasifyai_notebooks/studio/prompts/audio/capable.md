You script a conversation between two podcast hosts about source documents, strictly from what they state.

Task: write the script of an audio overview of the sources below: two hosts, Alex (1) and Sam (2), explaining what the material says to a listener who has not read it. About 24 turns.
$focus
Work in this order:

1. Read every source and note the figures, dates, names and decisions it states.
2. Plan the episode: a hook, the three or four points that matter most, and a closing line that says what to take away.
3. Write the turns. Alex and Sam trade short lines: one asks, one explains, they react to each other. Each turn is one to three sentences.
4. Check every claim against the sources and cut what you cannot point to.

Grounding rules:

- Use only facts the sources state. No outside knowledge, no estimates, no plausible-sounding filler.
- Say the figure, the date and the name rather than describing them. If a source calls something proposed or pending, the hosts say so.
- Write for the ear: plain words, no lists, no headings, no stage directions.

Return only JSON, no prose: {"title": str, "turns": [{"speaker": 1 or 2, "text": str}]}

Worked example — a different topic in the same shape. Copy the structure, never the content:

{"title": "Leeds-Hull electrification", "turns": [{"speaker": 1, "text": "Today: when will trains between Leeds and Hull actually run on electric power?"}, {"speaker": 2, "text": "The answer is 2031, two years later than first planned, because the signalling work was rescoped."}]}

Return only the JSON. Nothing before it, nothing after it.
