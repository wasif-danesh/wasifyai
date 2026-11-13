"""The wire format of Motion graphics jobs (ADR-0087, stage P4): the API's `RemoteBuilderEngine` and
the worker's handlers share these names. A composition travels as its template and its slots (the
page is made from them on the worker, which has the library and the fonts); what comes back is
numbers, a report, a still or the finished video."""

INSPECT = "builder.inspect"  # template + slots + spec in; the exact-text report out (meta)
SNAPSHOT = "builder.snapshot"  # template + slots + `at` in; one PNG out (`still`)
RENDER = "builder.render"  # template + slots + format in; the video out (`video`) and the numbers
LINT = "builder.lint"  # an HTML page in (params `html`); the findings out (meta)
KIT = "builder.kit"  # nothing in; the library, the player's runtime and the fonts out, one per file
KINDS = [INSPECT, SNAPSHOT, RENDER, LINT, KIT]
COMPONENT = "video_builder"  # the key of a worker's `components` entry
