"""Observed interval support. No extrapolation beyond the final sample or across long gaps."""

import numpy as np


def supported_minutes(frame):
    if frame.empty:
        return np.array([], dtype=float)
    delta = frame.timestamp.diff().dt.total_seconds().to_numpy() / 60
    on = frame.engine_on.to_numpy(bool)
    previous = np.r_[False, on[:-1]]
    return np.where((delta > 0) & (delta <= 10) & on & previous, delta, 0.0)


def counters(frame):
    minutes = supported_minutes(frame)
    previous_speed = frame.vehicle_speed_kmh.shift().fillna(0).to_numpy(float)
    return np.cumsum(minutes / 60), np.cumsum(previous_speed * minutes / 60)
