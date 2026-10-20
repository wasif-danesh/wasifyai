"""Video Builder (ADR-0077, stage V1c): videos written as HTML, rendered in a sandbox.

It lives inside the video product because what it makes are videos: a render is a `video` in the
library (mode "composition"), found by search and kept like any clip. The render engine itself is
the desktop component (`state.video_builder`, installed on request); this package imports nothing
from the API."""
