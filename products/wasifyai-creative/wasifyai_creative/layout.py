# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""Where the cuts fall (ADR-0090 decision 5). A pure function of what was found in the song: cuts on downbeats
and at the starts of sections, snapped to the video's frame grid. A stretch longer than the longest clip is split at
a beat, so a shot can always be made. `cut_speed` runs from -2 (few, long shots) to +2 (many, short ones)."""

from dataclasses import dataclass

FPS = 24  # the frame grid of the cut
LONGEST_CLIP_S = 5.0  # LTX at the final setting makes 5 s (docs/spikes/creative-cs0.md)
SHORTEST_S = 1.5  # a shot shorter than this cannot be read
BARS_AT_SPEED = {-2: 8, -1: 4, 0: 2, 1: 1}  # bars between cuts; +2 cuts on every other beat


@dataclass(frozen=True)
class Slot:
    start: float
    end: float


def _grid(t: float) -> float:
    return round(round(t * FPS) / FPS, 3)


def _wanted_cuts(
    beats: list[float], downbeats: list[float], starts: list[float], cut_speed: int
) -> list[float]:
    if cut_speed >= 2:
        return beats[::2]
    bars = BARS_AT_SPEED[max(cut_speed, -2)]
    if downbeats:
        return downbeats[::bars]
    return beats[:: bars * 4]  # no bars were found: count in fours


def _nearest(t: float, among: list[float]) -> float:
    return min(among, key=lambda x: abs(x - t)) if among else t


def lay_out(
    beats: list[float],
    downbeats: list[float],
    seconds: float,
    section_starts: list[float] | None = None,
    cut_speed: int = 0,
    longest: float = LONGEST_CLIP_S,
) -> list[Slot]:
    """Slots that cover the song from 0 to `seconds` with no gap, each from `SHORTEST_S` (unless the song
    itself is shorter) to `longest`."""
    if seconds <= 0:
        return []
    cut_speed = max(-2, min(2, cut_speed))
    bars = downbeats or beats
    sections = [_nearest(s, bars) for s in section_starts or [] if s > 0]
    wanted = sorted({*_wanted_cuts(beats, downbeats, section_starts or [], cut_speed), *sections})
    cuts = [0.0]
    for t in wanted:
        if t - cuts[-1] >= SHORTEST_S and seconds - t >= SHORTEST_S:
            cuts.append(t)
    cuts.append(seconds)
    out: list[Slot] = []
    for a, b in zip(cuts, cuts[1:], strict=False):
        at = a
        while b - at > longest:
            # the last beat that keeps both this shot and what is left long enough
            inner = [
                t for t in beats if at + SHORTEST_S <= t <= at + longest and b - t >= SHORTEST_S
            ]
            step = inner[-1] if inner else min(at + longest, b - SHORTEST_S)
            out.append(Slot(_grid(at), _grid(step)))
            at = step
        out.append(Slot(_grid(at), _grid(b)))
    return out
