// Not in a client component: a server page imports it, and a constant exported from a "use client" file reaches a
// server component as a reference, not as its value.
/** The address of a notebook that is not saved yet: `/notebooks/new`. */
export const NEW_NOTEBOOK = "new";
