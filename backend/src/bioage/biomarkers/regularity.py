"""Sleep regularity as the circular standard deviation of sleep midpoints.

Clock times live on a circle. Midpoints of 23:50 and 00:10 differ by 20 minutes, but as
raw minute-of-day values (1430 and 10) a linear standard deviation reports a difference
of 1420. Mapping each time to a unit vector and taking the resultant length gives the
standard circular SD:

    R     = |mean(exp(i * theta))|
    SD    = sqrt(-2 * ln(R))        (in radians)

which is then converted back to minutes.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

MINUTES_PER_DAY = 1440.0
MIN_NIGHTS = 3


def sleep_regularity_minutes(midpoints_min: Sequence[float]) -> float | None:
    """Circular standard deviation of sleep midpoints, in minutes.

    Larger values mean a more irregular sleep schedule. Returns None below MIN_NIGHTS,
    where the statistic is not meaningful.
    """
    if len(midpoints_min) < MIN_NIGHTS:
        return None

    angles = [
        2.0 * math.pi * (m % MINUTES_PER_DAY) / MINUTES_PER_DAY for m in midpoints_min
    ]
    mean_cos = sum(math.cos(a) for a in angles) / len(angles)
    mean_sin = sum(math.sin(a) for a in angles) / len(angles)
    resultant = math.hypot(mean_cos, mean_sin)

    if resultant <= 0.0:
        # Perfectly uniform around the clock: maximal irregularity.
        return MINUTES_PER_DAY / 2.0
    if resultant >= 1.0:
        return 0.0

    sd_radians = math.sqrt(-2.0 * math.log(resultant))
    sd_minutes = sd_radians * MINUTES_PER_DAY / (2.0 * math.pi)
    return min(sd_minutes, MINUTES_PER_DAY / 2.0)
