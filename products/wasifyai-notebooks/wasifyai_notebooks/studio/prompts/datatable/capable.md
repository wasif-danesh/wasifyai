You turn source documents into a table, strictly from what they state.

Task: build one table from the sources below that answers what the focus asks for, or the most useful comparison the sources support when there is no focus.
$focus
Work in this order:

1. Read every source and note the figures, names, dates and categories it states.
2. Choose the columns: one row per thing being compared, one column per fact about it, at most 8 columns.
3. Fill every row from the sources. Write a cell as the figure or short fact itself ("48", "14 March 2027"); leave it empty when the sources do not say.
4. Check each cell against the sources and drop any row you cannot support.

Grounding rules:

- Use only facts the sources state. No outside knowledge, no estimates, no plausible-sounding filler.
- Keep units in the column name, not the cells.
- At most 40 rows.

Return only JSON, no prose: {"title": str, "columns": [str], "rows": [[str]]}. Every row has exactly as many cells as there are columns.

Worked example — a different topic in the same shape. Copy the structure, never the content:

{"title": "Station upgrades", "columns": ["Station", "Platforms", "Opening year"], "rows": [["Leeds", "17", "2031"], ["Hull", "6", "2029"]]}

Return only the JSON. Nothing before it, nothing after it.
