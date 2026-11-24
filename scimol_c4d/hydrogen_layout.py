"""Place hydrogens around a fixed display skeleton using local geometry only.

Clearance is measured in the record's geometry units (approximately Angstroms).
These small soft radii separate atom centers; they do not represent displayed
sphere radii, which can intentionally overlap in space-fill mode.
"""

from __future__ import annotations

import math


CLEARANCE_RADII = {"H": .75, "C": .95, "N": .90, "O": .85,
                   "F": .85, "P": 1.0, "S": 1.0, "CL": 1.0,
                   "BR": 1.05, "I": 1.1}
DEFAULT_CLEARANCE_RADIUS = .95
_EPS = 1e-10


def _add(a, b):
    return [a[i] + b[i] for i in range(3)]


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _scale(vector, factor):
    return [value * factor for value in vector]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0]]


def _length(vector):
    return math.sqrt(_dot(vector, vector))


def _unit(vector):
    length = _length(vector)
    return _scale(vector, 1. / length) if length > _EPS else None


def _perpendicular(axis, preferred=None):
    if preferred is not None:
        projected = _sub(preferred, _scale(axis, _dot(axis, preferred)))
        candidate = _unit(projected)
        if candidate is not None:
            return candidate
    reference = min(([1., 0., 0.], [0., 1., 0.], [0., 0., 1.]),
                    key=lambda item: abs(_dot(item, axis)))
    return _unit(_sub(reference, _scale(axis, _dot(axis, reference))))


def rotate_about_axis(vector, axis, angle):
    """Rotate a vector by radians around an axis, preserving its length."""
    unit = _unit(axis)
    if unit is None:
        raise ValueError("旋转轴长度接近零")
    if not math.isfinite(angle) or any(not math.isfinite(v) for v in vector):
        raise ValueError("旋转输入必须有限")
    cosine, sine = math.cos(angle), math.sin(angle)
    return [_scale(vector, cosine)[i] +
            _scale(_cross(unit, vector), sine)[i] +
            unit[i] * _dot(unit, vector) * (1. - cosine)
            for i in range(3)]


def _align_direction(vector, old_axis, new_axis, normal):
    """Carry a source H direction with its heavy bond, including a half turn."""
    cosine = max(-1., min(1., _dot(old_axis, new_axis)))
    rotation_axis = _cross(old_axis, new_axis)
    sine = _length(rotation_axis)
    if sine > _EPS:
        return rotate_about_axis(vector, rotation_axis, math.atan2(sine, cosine))
    if cosine < 0.:
        return rotate_about_axis(vector, _perpendicular(old_axis, normal), math.pi)
    return vector


def _edges(bonds):
    for bond in bonds:
        if isinstance(bond, dict):
            yield int(bond["a"]), int(bond["b"])
        else:
            yield int(bond[0]), int(bond[1])


def collision_score(positions, elements, bonds, pairs=None):
    """Deterministic squared penalty for nonbonded atom centers inside soft radii."""
    bonded = {tuple(sorted(edge)) for edge in _edges(bonds)}
    if pairs is None:
        ids = sorted(positions)
        pairs = ((a, b) for index, a in enumerate(ids) for b in ids[index+1:])
    total = 0.
    for first, second in sorted({tuple(sorted((int(a), int(b)))) for a, b in pairs}):
        if first == second or (first, second) in bonded:
            continue
        if first not in positions or second not in positions:
            raise ValueError("碰撞评分引用了不存在的原子")
        radius_a = CLEARANCE_RADII.get(str(elements[first]).upper(), DEFAULT_CLEARANCE_RADIUS)
        radius_b = CLEARANCE_RADII.get(str(elements[second]).upper(), DEFAULT_CLEARANCE_RADIUS)
        clearance = radius_a + radius_b - _length(_sub(positions[first], positions[second]))
        if clearance > 0:
            total += clearance * clearance
    return total


def _candidate_directions(element, hydrogens, heavy_neighbors, heavy_bonds,
                          source, moved, parent, normal):
    """Yield ordered local direction families; a family moves all sibling H."""
    count = len(hydrogens)
    neighbors = [_unit(_sub(moved[item], moved[parent])) for item in heavy_neighbors]
    neighbors = [item for item in neighbors if item is not None]
    outward_sum = _scale([sum(item[i] for item in neighbors) for i in range(3)], -1.)
    outward_degenerate = _length(outward_sum) < 1e-5
    outward = None if outward_degenerate else _unit(outward_sum)
    source_vectors = [_unit(_sub(source[item], source[parent])) for item in hydrogens]
    source_vectors = [item or normal for item in source_vectors]
    if outward is None:
        outward = _perpendicular(neighbors[0], normal) if neighbors else _perpendicular(normal)
    in_plane = _unit(_sub(outward, _scale(normal, _dot(outward, normal))))
    if in_plane is None:
        # Opposing heavy bonds have no outward bisector. Pick the transverse
        # direction in the molecular plane rather than pointing at a bond.
        in_plane = (_unit(_cross(normal, neighbors[0])) if neighbors else None)
        if in_plane is None:
            in_plane = _perpendicular(normal)

    if element == "C" and count == 2 and len(neighbors) == 1 and any(
            order > 1.1 or aromatic for order, aromatic in heavy_bonds):
        # A terminal alkene CH2 has both C-H bonds in the alkene plane.
        transverse = _unit(_cross(normal, in_plane))
        if transverse is None:
            transverse = _perpendicular(in_plane)
        for sign in (1., -1.):
            yield [_add(_scale(in_plane, .5),
                        _scale(transverse, sign * math.sqrt(3.) / 2.)),
                   _add(_scale(in_plane, .5),
                        _scale(transverse, -sign * math.sqrt(3.) / 2.))]
    elif element == "O" and count == 1 and len(neighbors) == 1:
        old_heavy = _unit(_sub(source[heavy_neighbors[0]], source[parent]))
        old_h = source_vectors[0]
        source_angle = (math.acos(max(-1., min(1., _dot(old_heavy, old_h))))
                        if old_heavy is not None else math.radians(110.))
        if (not math.isfinite(source_angle) or source_angle < math.radians(20.) or
                source_angle > math.radians(160.)):
            source_angle = math.radians(110.)
        center_angle = min(math.radians(120.), max(math.radians(105.), source_angle))
        transverse = _unit(_cross(normal, neighbors[0]))
        if transverse is None:
            transverse = _perpendicular(neighbors[0])
        source_side = (1. if old_heavy is None or
                       _dot(_cross(old_heavy, old_h), normal) >= 0. else -1.)
        for side in (source_side, -source_side):
            for offset in (0., math.radians(5.), -math.radians(5.)):
                angle = min(math.radians(120.), max(math.radians(105.),
                                                    center_angle + offset))
                yield [_add(_scale(neighbors[0], math.cos(angle)),
                            _scale(transverse, side * math.sin(angle)))]
    elif element == "C" and count == 3 and len(neighbors) == 1:
        axis = neighbors[0]
        side = _perpendicular(axis, normal)
        other = _unit(_cross(axis, side))
        for phase in range(12):
            angle = math.pi * phase / 6.
            directions = []
            for index in range(3):
                theta = angle + 2. * math.pi * index / 3.
                radial = _add(_scale(side, math.cos(theta)),
                              _scale(other, math.sin(theta)))
                directions.append(_add(_scale(axis, -1. / 3.),
                                       _scale(radial, math.sqrt(8.) / 3.)))
            yield directions
    elif element == "C" and count == 2 and len(neighbors) >= 2:
        cosine_half = _length(_add(neighbors[0], neighbors[1])) / 2.
        along = min(.65, max(.25, 1. / max(3. * cosine_half, .01)))
        across = math.sqrt(1. - along * along)
        for sign in (1., -1.):
            yield [_add(_scale(in_plane, along), _scale(normal, sign * across)),
                   _add(_scale(in_plane, along), _scale(normal, -sign * across))]
    elif count == 1:
        sp2 = (element == "C" and len(neighbors) == 2 and
               any(order > 1.1 or aromatic for order, aromatic in heavy_bonds))
        if sp2:
            for angle in (0., math.radians(12), -math.radians(12)):
                yield [rotate_about_axis(in_plane, normal, angle)]
        else:
            side = 1. if _dot(source_vectors[0], normal) >= 0 else -1.
            if element == "C" and len(heavy_neighbors) == 3:
                first, second, third = heavy_neighbors
                source_base = source[third]
                moved_base = moved[third]
                source_volume = _dot(
                    _cross(_sub(source[first], source_base),
                           _sub(source[second], source_base)),
                    _sub(source[hydrogens[0]], source_base))
                moved_area = _dot(
                    _cross(_sub(moved[first], moved_base),
                           _sub(moved[second], moved_base)), normal)
                if abs(source_volume) > 1e-8 and abs(moved_area) > 1e-8:
                    side = 1. if source_volume * moved_area > 0. else -1.
            if element == "C" and len(neighbors) >= 3 and outward_degenerate:
                yield [_scale(normal, side)]
            else:
                for height in (.8, 1.1, .5):
                    yield [_unit(_add(in_plane, _scale(normal, side * height)))]
    else:
        # Keep unusual valences' internal H arrangement while following the
        # changed heavy-bond axis instead of freezing source world directions.
        if heavy_neighbors and neighbors:
            old_axis = _unit(_sub(source[heavy_neighbors[0]], source[parent]))
            if old_axis is not None:
                yield [_align_direction(vector, old_axis, neighbors[0], normal)
                       for vector in source_vectors]
                return
        yield source_vectors


def arrange_hydrogens(record, source_positions, moved_positions,
                      selected_heavy, normal):
    """Return copied int-keyed positions after arranging H on selected atoms.

    Candidate families preserve each source X-H bond length. Their fixed,
    bounded search uses the new heavy-neighbor directions and scores only local
    nonbonded contacts. The source conformer and heavy centers are untouched.
    """
    source = {int(key): [float(v) for v in xyz] for key, xyz in source_positions.items()}
    moved = {int(key): [float(v) for v in xyz] for key, xyz in moved_positions.items()}
    if set(source) != set(moved):
        raise ValueError("原始与显示坐标的原子集合不一致")
    plane_normal = _unit(normal)
    if plane_normal is None or any(not math.isfinite(v) for xyz in (*source.values(), *moved.values())
                                  for v in xyz):
        raise ValueError("平面法线或原子坐标无效")
    atoms = {atom["id"]: atom for atom in record["atoms"]}
    if set(atoms) != set(source):
        raise ValueError("结构记录的原子集合不一致")
    graph = {atom_id: set() for atom_id in atoms}
    heavy_bonds = {atom_id: [] for atom_id in atoms}
    for bond in record["bonds"]:
        a, b = int(bond["a"]), int(bond["b"])
        graph[a].add(b); graph[b].add(a)
        order, aromatic = float(bond.get("order", 1.)), bool(bond.get("aromatic"))
        heavy_bonds[a].append((order, aromatic)); heavy_bonds[b].append((order, aromatic))
    chosen = sorted({int(item) for item in selected_heavy})
    if any(item not in atoms or atoms[item]["element"].upper() == "H" for item in chosen):
        raise ValueError("所选原子必须是有效重原子")
    selected_h = {neighbor for atom_id in chosen for neighbor in graph[atom_id]
                  if atoms[neighbor]["element"].upper() == "H"}
    # Rebuild this canonical starting state on every call, including repeats.
    for hydrogen in selected_h:
        parent = next(item for item in graph[hydrogen] if item in chosen)
        moved[hydrogen] = _add(moved[parent], _sub(source[hydrogen], source[parent]))
    elements = {atom_id: atom["element"] for atom_id, atom in atoms.items()}
    for parent in chosen:
        hydrogens = sorted(item for item in graph[parent]
                           if atoms[item]["element"].upper() == "H")
        if not hydrogens:
            continue
        heavy_neighbors = sorted(item for item in graph[parent]
                                 if atoms[item]["element"].upper() != "H")
        lengths = [_length(_sub(source[item], source[parent])) for item in hydrogens]
        if any(length <= _EPS for length in lengths):
            raise ValueError("原始 X-H 键长接近零")
        source_units = [_unit(_sub(source[item], source[parent])) for item in hydrogens]
        reference_units = source_units
        if heavy_neighbors:
            old_axis = _unit(_sub(source[heavy_neighbors[0]], source[parent]))
            new_axis = _unit(_sub(moved[heavy_neighbors[0]], moved[parent]))
            if old_axis is not None and new_axis is not None:
                reference_units = [_align_direction(vector, old_axis, new_axis,
                                                    plane_normal)
                                   for vector in source_units]
        pairs = [(hydrogen, other) for hydrogen in hydrogens for other in moved
                 if other != hydrogen]
        ranked = []
        for index, directions in enumerate(_candidate_directions(
                atoms[parent]["element"].upper(), hydrogens, heavy_neighbors,
                [next((float(bond.get("order", 1.)), bool(bond.get("aromatic")))
                      for bond in record["bonds"] if {bond["a"], bond["b"]} == {parent, neighbor})
                 for neighbor in heavy_neighbors],
                source, moved, parent, plane_normal)):
            if len(directions) != len(hydrogens) or any(direction is None for direction in directions):
                continue
            candidate = dict(moved)
            for hydrogen, length, direction in zip(hydrogens, lengths, directions):
                candidate[hydrogen] = _add(moved[parent], _scale(_unit(direction), length))
            score = collision_score(candidate, elements, record["bonds"], pairs)
            source_change = sum(_length(_sub(_unit(direction), original))**2
                                for direction, original in zip(directions, reference_units))
            ranked.append((score, source_change, index, candidate))
        if not ranked:
            raise ValueError("无法确定氢原子的显示方向")
        moved = min(ranked, key=lambda item: item[:3])[3]
    return moved
