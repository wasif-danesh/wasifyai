"""The wire format of a song's analysis on an engine worker (ADR-0090, the web): the API's
`RemoteMusicAnalysis` and the worker's handler share these names. The recording is a file in object
storage; the beats, downbeats, tempo and sections come back as `meta`."""

ANALYSE = "analysis.song"  # a WAV in (`song`); the analysis out (meta)
KINDS = [ANALYSE]
COMPONENT = "music_analysis"  # the key of a worker's `components` entry
SETUP = "music-analysis"  # the name `admin.fetch_engine` takes to set it up
