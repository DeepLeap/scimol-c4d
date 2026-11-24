"""Readable display units; chemistry and saved styles keep physical radii."""
import math

_SCALES = {
    "atom_radius": ((1., .30), (5., 1.)),
    "bond_radius": ((1., .05), (2., .08), (5., .18)),
    "bond_spacing": ((1., .10), (2., .18), (5., .40)),
}


def display_limits(key):
    return (_SCALES[key][0][0], _SCALES[key][-1][0])


def _interpolate(points, value):
    if value < points[0][0]:
        return value * points[0][1] / points[0][0]
    pair = (points[-2], points[-1])
    for a, b in zip(points, points[1:]):
        if value <= b[0]:
            pair = (a, b)
            break
    a, b = pair
    return a[1] + (value-a[0])*(b[1]-a[1])/(b[0]-a[0])


def to_physical(key, value):
    value = float(value)
    result = _interpolate(_SCALES[key], value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("尺寸必须为正数")
    return result


def to_display(key, value):
    value = float(value)
    return _interpolate(tuple((physical, display) for display, physical in _SCALES[key]), value)
