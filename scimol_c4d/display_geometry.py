"""Pure-Python display coordinate overrides for molecular flattening.

The chemical record is never modified. Coordinates are in the record's original
coordinate system and remain absolute Angstrom positions.
"""

from __future__ import annotations

import math
from collections import deque
from statistics import median

from .hydrogen_layout import arrange_hydrogens, collision_score, rotate_about_axis


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _length(a):
    return math.sqrt(_dot(a, a))


def _center(points):
    return [sum(p[i] for p in points) / len(points) for i in range(3)]


def _plane(points):
    """Centroid and least-variance unit normal of a small point cloud."""
    origin = _center(points)
    if len(points) == 1:
        return origin, [0.0, 0.0, 1.0]
    if len(points) == 2:
        direction = _sub(points[1], points[0])
        axis = min(range(3), key=lambda i: abs(direction[i]))
        normal = [0.0, 0.0, 0.0]
        normal[axis] = 1.0
        projection = _dot(normal, direction) / max(_dot(direction, direction), 1e-30)
        normal = _sub(normal, [projection * d for d in direction])
        norm = math.sqrt(_dot(normal, normal))
        return origin, [v / norm for v in normal]

    centered = [_sub(p, origin) for p in points]
    matrix = [[sum(p[i] * p[j] for p in centered) for j in range(3)] for i in range(3)]
    vectors = [[float(i == j) for j in range(3)] for i in range(3)]
    for _ in range(32):
        i, j = max(((0, 1), (0, 2), (1, 2)), key=lambda pair: abs(matrix[pair[0]][pair[1]]))
        if abs(matrix[i][j]) < 1e-12:
            break
        tau = (matrix[j][j] - matrix[i][i]) / (2.0 * matrix[i][j])
        t = (1.0 if tau >= 0 else -1.0) / (abs(tau) + math.sqrt(1.0 + tau * tau))
        c = 1.0 / math.sqrt(1.0 + t * t)
        s = t * c
        aii, ajj, aij = matrix[i][i], matrix[j][j], matrix[i][j]
        matrix[i][i] = aii - t * aij
        matrix[j][j] = ajj + t * aij
        matrix[i][j] = matrix[j][i] = 0.0
        for k in range(3):
            if k != i and k != j:
                aki, akj = matrix[k][i], matrix[k][j]
                matrix[k][i] = matrix[i][k] = c * aki - s * akj
                matrix[k][j] = matrix[j][k] = s * aki + c * akj
            vki, vkj = vectors[k][i], vectors[k][j]
            vectors[k][i] = c * vki - s * vkj
            vectors[k][j] = s * vki + c * vkj
    index = min(range(3), key=lambda i: matrix[i][i])
    normal = [vectors[i][index] for i in range(3)]
    return origin, normal


def ring_center_options(record):
    """Return bounded, deterministic local heavy-atom rings for center selection.

    All equally shortest cycles through each bond find the local faces of
    fused or bridged rings without enumerating large outer perimeters.
    """
    if not isinstance(record, dict):
        return []
    atoms, bonds = record.get("atoms"), record.get("bonds")
    if not isinstance(atoms, list) or not isinstance(bonds, list):
        return []
    elements = {atom.get("id"): str(atom.get("element", "")).upper()
                for atom in atoms if isinstance(atom, dict) and
                isinstance(atom.get("id"), int) and not isinstance(atom.get("id"), bool)}
    heavy = {atom_id for atom_id, element in elements.items() if element and element != "H"}
    if len(heavy) < 3 or len(heavy) > 256 or len(bonds) > 1200:
        return []
    graph = {atom_id: set() for atom_id in heavy}
    aromatic_edges = set()
    for bond in bonds:
        if not isinstance(bond, dict):
            continue
        a, b = bond.get("a"), bond.get("b")
        if (isinstance(a, bool) or not isinstance(a, int) or
                isinstance(b, bool) or not isinstance(b, int)):
            continue
        if a not in graph or b not in graph or a == b:
            continue
        graph[a].add(b)
        graph[b].add(a)
        if bond.get("aromatic"):
            aromatic_edges.add(tuple(sorted((a, b))))
    edges = sorted((a, b) for a in graph for b in graph[a] if a < b)
    if len(edges) > 1200:
        return []
    neighbors = {atom_id: sorted(items) for atom_id, items in graph.items()}
    cycles = {}
    remaining_paths = 128
    remaining_steps = 4096
    for a, b in edges:
        # Search with this bond removed, retaining all equally short predecessors.
        distance = {a: 0}
        predecessors = {a: []}
        queue = deque([a])
        while queue:
            node = queue.popleft()
            if b in distance and distance[node] >= distance[b]:
                break
            for adjacent in neighbors[node]:
                if (node == a and adjacent == b) or (node == b and adjacent == a):
                    continue
                next_distance = distance[node] + 1
                if adjacent not in distance:
                    distance[adjacent] = next_distance
                    predecessors[adjacent] = [node]
                    queue.append(adjacent)
                elif distance[adjacent] == next_distance:
                    predecessors[adjacent].append(node)
        if b not in distance or distance[b] < 2:
            continue
        stack = [(b, [b])]
        while stack and remaining_paths and remaining_steps:
            remaining_steps -= 1
            node, path = stack.pop()
            if node != a:
                for previous in reversed(predecessors[node]):
                    stack.append((previous, path + [previous]))
                continue
            remaining_paths -= 1
            key = tuple(sorted(path))
            perimeter = list(zip(path, path[1:] + path[:1]))
            aromatic = all(tuple(sorted(edge)) in aromatic_edges for edge in perimeter)
            benzene = aromatic and len(path) == 6 and all(elements[item] == "C" for item in path)
            category = 0 if benzene else 1 if aromatic else 2
            previous = cycles.get(key)
            if previous is None or category < previous:
                cycles[key] = category
        if not remaining_paths or not remaining_steps:
            break
    names = {3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八"}
    counts = {}
    result = []
    # UI order is also the automatic center priority. A six-membered
    # heterocycle outranks a smaller aromatic ring, but is never benzene.
    def ring_priority(item):
        atom_ids, category = item
        tier = 0 if category == 0 else 1 if len(atom_ids) == 6 else 2
        return tier, category, len(atom_ids), atom_ids

    for atom_ids, category in sorted(cycles.items(), key=ring_priority):
        size = names.get(len(atom_ids), str(len(atom_ids)))
        base = "苯环" if category == 0 else ("芳香" if category == 1 else "") + size + "元环"
        counts[base] = counts.get(base, 0) + 1
        result.append({"atom_ids": list(atom_ids), "label": base + str(counts[base])})
    return result


def _planar_ring(ids, positions, bonds, prefer_six=False):
    """Choose a near-planar ring in a bounded DFS cycle basis.

    One fundamental cycle is examined per non-tree edge, so at most E-V+C
    candidates are fitted. This deliberately does not enumerate every simple
    cycle in a fused graph.
    """
    graph = {atom_id: set() for atom_id in ids}
    for bond in bonds:
        a, b = bond["a"], bond["b"]
        if a in graph and b in graph:
            graph[a].add(b)
            graph[b].add(a)
    best = None
    parent = {}
    active = set()
    for start in sorted(graph):
        if start in parent:
            continue
        parent[start] = None
        active.add(start)
        stack = [(start, iter(sorted(graph[start])))]
        while stack:
            node, neighbors = stack[-1]
            neighbor = next(neighbors, None)
            if neighbor is None:
                active.remove(node)
                stack.pop()
                continue
            if neighbor == parent[node]:
                continue
            if neighbor not in parent:
                parent[neighbor] = node
                active.add(neighbor)
                stack.append((neighbor, iter(sorted(graph[neighbor]))))
                continue
            if neighbor not in active:
                continue
            path = [node]
            ancestor = parent[node]
            while ancestor != neighbor and ancestor is not None and len(path) < 12:
                path.append(ancestor)
                ancestor = parent[ancestor]
            if ancestor != neighbor:
                continue
            path.append(neighbor)
            if not 3 <= len(path) <= 12:
                continue
            points = [positions[item] for item in path]
            origin, normal = _plane(points)
            deviation = max(abs(_dot(_sub(p, origin), normal)) for p in points)
            score = (len(path) == 6, len(path), -deviation) if prefer_six else (len(path), -deviation)
            best_score = ((len(best[0]) == 6, len(best[0]), -best[3]) if prefer_six
                          else (len(best[0]), -best[3])) if best else None
            if deviation < 0.15 and (best is None or score > best_score):
                best = (path, origin, normal, deviation)
    return best


def _major_axis(points, normal):
    """Dominant in-plane spread direction, with a deterministic sign."""
    center = _center(points)
    axis = min(range(3), key=lambda i: abs(normal[i]))
    basis = [float(i == axis) for i in range(3)]
    u = _sub(basis, [normal[i] * _dot(basis, normal) for i in range(3)])
    u = [v / _length(u) for v in u]
    v = _cross(normal, u)
    projected = [(_dot(_sub(point, center), u), _dot(_sub(point, center), v))
                 for point in points]
    xx = sum(x*x for x, _ in projected)
    yy = sum(y*y for _, y in projected)
    xy = sum(x*y for x, y in projected)
    angle = .5 * math.atan2(2. * xy, xx - yy)
    result = [math.cos(angle) * u[i] + math.sin(angle) * v[i] for i in range(3)]
    farthest = max(points, key=lambda point: _dot(_sub(point, center), _sub(point, center)))
    if _dot(result, _sub(farthest, center)) < 0:
        result = [-value for value in result]
    return result


def _acyclic_reference(record, heavy, positions, center_id=None):
    """Choose a heavy-graph center and a real outward bond for an acyclic view."""
    elements = {atom["id"]: atom["element"].upper() for atom in record["atoms"]}
    graph = {atom_id: set() for atom_id in heavy}
    all_neighbors = {atom_id: set() for atom_id in positions}
    for bond in record["bonds"]:
        a, b = bond["a"], bond["b"]
        if a in all_neighbors and b in all_neighbors and a != b:
            all_neighbors[a].add(b)
            all_neighbors[b].add(a)
            if a in graph and b in graph:
                graph[a].add(b)
                graph[b].add(a)

    if center_id is None and heavy:
        components = []
        unseen = set(heavy)
        while unseen:
            start = min(unseen)
            component = {start}
            queue = deque([start])
            unseen.remove(start)
            while queue:
                for neighbor in sorted(graph[queue.popleft()] & unseen):
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
            components.append(component)
        component = min(components, key=lambda items: (-len(items), min(items)))
        scores = []
        for atom_id in sorted(component):
            distances = {atom_id: 0}
            queue = deque([atom_id])
            while queue:
                node = queue.popleft()
                for neighbor in sorted(graph[node] & component):
                    if neighbor not in distances:
                        distances[neighbor] = distances[node] + 1
                        queue.append(neighbor)
            scores.append((max(distances.values()), sum(distances.values()),
                           elements[atom_id] != "C", atom_id))
        center_id = min(scores)[3]
    if center_id is None:
        return None, None, None

    candidates = sorted(all_neighbors[center_id] & heavy)
    if not candidates:
        candidates = sorted(all_neighbors[center_id])
    if not candidates:
        return center_id, None, None

    def branch_depth(neighbor):
        found = {center_id, neighbor}
        queue = deque([(neighbor, 0)])
        depth = 0
        while queue:
            node, distance = queue.popleft()
            depth = max(depth, distance)
            for other in sorted(graph.get(node, ())):
                if other not in found:
                    found.add(other)
                    queue.append((other, distance + 1))
        return depth

    axis_id = min(candidates, key=lambda item: (elements[item] != "C",
                                                -branch_depth(item), item))
    source_x = _sub(positions[axis_id], positions[center_id])
    if _length(source_x) < 1e-9:
        return center_id, None, None
    secondary = sorted((all_neighbors[center_id] & heavy) - {axis_id})
    secondary += [item for item in sorted(heavy) if item not in secondary and
                  item not in (center_id, axis_id)]
    for item in secondary:
        normal = _cross(source_x, _sub(positions[item], positions[center_id]))
        if _length(normal) > 1e-9:
            return center_id, source_x, normal
    return center_id, source_x, None


def orient_display_positions(record, positions, orientation="original", center_atom_ids=None):
    """Center and rigidly orient display coordinates, without editing chemistry.

    Positions are absolute Angstrom coordinates, including any planar edits.
    A fitted aromatic/planar ring supplies the reference plane when available;
    the preset rotates the entire molecule rather than projecting its atoms.
    """
    if orientation not in ("original", "auto", "xy", "xz", "yz"):
        raise ValueError("整体朝向无效")
    ids = {atom["id"] for atom in record["atoms"]}
    if set(positions) != ids or any(len(positions[item]) != 3 or
                                     not all(math.isfinite(float(v)) for v in positions[item])
                                     for item in ids):
        raise ValueError("整体朝向的原子坐标无效")
    centers = [] if center_atom_ids is None else center_atom_ids
    if (not isinstance(centers, list) or len(centers) > len(ids) or
            any(isinstance(item, bool) or not isinstance(item, int) or item not in ids
                for item in centers)):
        raise ValueError("中心原子无效")
    heavy = {atom["id"] for atom in record["atoms"] if atom["element"].upper() != "H"}
    options = ring_center_options(record)
    selected = set(centers)
    chosen = next((option for option in options if set(option["atom_ids"]) == selected), None)
    if chosen is None and not centers:
        for option in options:
            ring_points = [positions[item] for item in option["atom_ids"]]
            ring_origin, ring_normal = _plane(ring_points)
            if max(abs(_dot(_sub(point, ring_origin), ring_normal))
                   for point in ring_points) < 0.15:
                chosen = option
                break
    ring = None
    if chosen:
        ring_ids = chosen["atom_ids"]
        ring_origin, ring_normal = _plane([positions[item] for item in ring_ids])
        ring = (ring_ids, ring_origin, ring_normal, 0.0)
    else:
        aromatic_bonds = [bond for bond in record["bonds"] if bond.get("aromatic")]
        prefer_six = orientation == "auto"
        selected_ring = (_planar_ring(selected & heavy, positions,
                                     aromatic_bonds or record["bonds"], prefer_six)
                         if len(centers) >= 3 else None)
        ring = selected_ring or (_planar_ring(heavy, positions, aromatic_bonds, prefer_six)
                                 if aromatic_bonds else None)
        if ring is None and heavy:
            ring = _planar_ring(heavy, positions, record["bonds"], prefer_six)
    if len(centers) == 1:
        ring = None
    acyclic = (_acyclic_reference(record, heavy, positions,
                                  centers[0] if centers else None)
               if ring is None and len(centers) <= 1 and orientation != "original" else None)
    if centers:
        origin = _center([positions[item] for item in centers])
    elif orientation != "original" and ring:
        origin = ring[1]
    elif acyclic and acyclic[0] is not None:
        origin = list(positions[acyclic[0]])
    else:
        origin = _center([positions[item] for item in sorted(ids)])
    shifted = {item: _sub(list(map(float, xyz)), origin) for item, xyz in positions.items()}
    if orientation == "original":
        return shifted

    reference_ids = sorted(heavy or ids)
    _, normal = (ring[1], ring[2]) if ring else _plane([positions[item] for item in reference_ids])
    if acyclic and acyclic[2] is not None:
        normal = acyclic[2]
    magnitude = _length(normal)
    normal = [v / magnitude for v in normal]
    if ring:
        ring_ids = set(ring[0])
        ring_edges = sorted((min(bond["a"], bond["b"]), max(bond["a"], bond["b"]))
                            for bond in record["bonds"]
                            if bond["a"] in ring_ids and bond["b"] in ring_ids and
                            bond["a"] != bond["b"])
        if ring_edges:
            first, second = ring_edges[0]
            source_x = _sub(positions[second], positions[first])
        else:
            source_x = _major_axis([positions[item] for item in ring[0]], normal)
    elif acyclic and acyclic[1] is not None:
        source_x = acyclic[1]
    elif orientation == "auto":
        source_x = _major_axis([positions[item] for item in reference_ids], normal)
    else:
        source_x = max((shifted[item] for item in reference_ids), key=_length)
    source_x = [source_x[i] - _dot(source_x, normal) * normal[i] for i in range(3)]
    if _length(source_x) < 1e-9:
        axis = min(range(3), key=lambda i: abs(normal[i]))
        basis = [float(i == axis) for i in range(3)]
        source_x = [basis[i] - _dot(basis, normal) * normal[i] for i in range(3)]
    source_x = [v / _length(source_x) for v in source_x]
    source_y = _cross(normal, source_x)
    target_normal = {"auto": [0., 0., 1.], "xy": [0., 0., 1.],
                     "xz": [0., 1., 0.], "yz": [1., 0., 0.]}[orientation]
    if acyclic and orientation == "xz":
        target_normal = [0., -1., 0.]
    target_x = [1., 0., 0.] if orientation != "yz" else [0., 1., 0.]
    target_y = _cross(target_normal, target_x)
    return {item: [
        _dot(xyz, source_x) * target_x[axis] +
        _dot(xyz, source_y) * target_y[axis] +
        _dot(xyz, normal) * target_normal[axis]
        for axis in range(3)] for item, xyz in shifted.items()}


def _record_positions(record):
    by_id = {atom["id"]: atom for atom in record["atoms"]}
    positions = {atom_id: [float(atom[axis]) for axis in ("x", "y", "z")]
                 for atom_id, atom in by_id.items()}
    if any(not all(math.isfinite(value) for value in xyz) for xyz in positions.values()):
        raise ValueError("原子坐标必须有限")
    heavy = {atom_id for atom_id, atom in by_id.items() if atom["element"].upper() != "H"}
    if not heavy:
        raise ValueError("结构没有可拍平的重原子")
    return by_id, positions, heavy


def _selected_heavy(atom_ids, by_id, heavy):
    if atom_ids is None or isinstance(atom_ids, (str, bytes)):
        raise ValueError("所选原子 id 列表无效")
    try:
        requested = list(atom_ids)
    except TypeError as exc:
        raise ValueError("所选原子 id 列表无效") from exc
    if any(not isinstance(atom_id, int) or isinstance(atom_id, bool) or atom_id not in by_id
           for atom_id in requested):
        raise ValueError("所选原子包含未知 id")
    selected = set(requested) & heavy
    if not selected:
        raise ValueError("所选原子只有氢或为空；请选择重原子")
    return selected


def _unit_normal(normal):
    if (not isinstance(normal, (list, tuple)) or len(normal) != 3 or
            any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in normal)):
        raise ValueError("平面法线必须是有限的三元组")
    length = math.hypot(*normal)
    if length <= 1e-12:
        raise ValueError("平面法线不能为零")
    return [float(v) / length for v in normal]


def _copy_overrides(existing_overrides, by_id):
    result = {}
    for key, xyz in (existing_overrides or {}).items():
        try:
            atom_id = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError("覆盖坐标包含未知 id") from exc
        if atom_id not in by_id or str(atom_id) != str(key):
            raise ValueError("覆盖坐标包含未知 id")
        if (not isinstance(xyz, (list, tuple)) or len(xyz) != 3 or
                any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in xyz)):
            raise ValueError("覆盖坐标必须是有限的三元组")
        result[str(atom_id)] = [float(v) for v in xyz]
    return result


def _graph(positions, bonds):
    graph = {atom_id: set() for atom_id in positions}
    for bond in bonds:
        a, b = bond["a"], bond["b"]
        graph[a].add(b)
        graph[b].add(a)
    return graph


def _cyclic_heavy(heavy, graph):
    cyclic = set()
    for a in heavy:
        for b in graph[a] & heavy:
            if a < b:
                graph[a].remove(b)
                graph[b].remove(a)
                connected = a in _component(graph, b, -1)
                graph[a].add(b)
                graph[b].add(a)
                if connected:
                    cyclic.update((a, b))
    return cyclic


def _component(graph, start, blocked):
    found = {start}
    todo = [start]
    while todo:
        for neighbor in graph[todo.pop()]:
            if neighbor != blocked and neighbor not in found:
                found.add(neighbor)
                todo.append(neighbor)
    return found


def _rotate_branch(current, parent, child, members, origin, normal):
    """Move a distal component rigidly about its fixed parent onto a plane."""
    pivot, tip = current[parent], current[child]
    vector = _sub(tip, pivot)
    length = _length(vector)
    if length < 1e-8:
        raise ValueError("化学键长度接近零；请换一个平面")
    offset = _dot(_sub(pivot, origin), normal)
    if abs(offset) > length + 1e-10:
        raise ValueError("连接键无法到达目标平面；请换一个平面")
    foot = [pivot[i] - offset*normal[i] for i in range(3)]
    radial = _sub(tip, foot)
    radial = [radial[i] - _dot(radial, normal)*normal[i] for i in range(3)]
    radial_length = _length(radial)
    if radial_length < 1e-10:
        basis = [1.0, 0.0, 0.0] if abs(normal[0]) < 0.8 else [0.0, 1.0, 0.0]
        radial = _cross(normal, basis)
        radial_length = _length(radial)
    radius = math.sqrt(max(0.0, length*length-offset*offset))
    target = [foot[i] + radius*radial[i]/radial_length for i in range(3)]
    desired = _sub(target, pivot)
    source_unit = [v/length for v in vector]
    target_unit = [v/length for v in desired]
    cosine = max(-1.0, min(1.0, _dot(source_unit, target_unit)))
    axis = _cross(source_unit, target_unit)
    sine = _length(axis)
    if sine < 1e-12:
        if cosine > 0:
            return
        basis = [1.0, 0.0, 0.0] if abs(source_unit[0]) < 0.8 else [0.0, 1.0, 0.0]
        axis = _cross(source_unit, basis)
        sine = _length(axis)
        cosine = -1.0
        angle_sine = 0.0
    else:
        angle_sine = sine
    axis = [v/sine for v in axis]
    for atom_id in members:
        v = _sub(current[atom_id], pivot)
        cross = _cross(axis, v)
        projection = _dot(axis, v)
        current[atom_id] = [pivot[i] + cosine*v[i] + angle_sine*cross[i] +
                            (1.0-cosine)*projection*axis[i] for i in range(3)]


def _rigid_flatten(positions, bonds, by_id, heavy, selected, origin, normal, result,
                   ring_ids=None, protected=None):
    graph = _graph(positions, bonds)
    current = {atom_id: result.get(str(atom_id), xyz)[:] for atom_id, xyz in positions.items()}
    ring_ids = set(ring_ids or ())
    protected = set(protected or ())
    if ring_ids:
        roots = sorted(ring_ids)
    else:
        roots = [min(heavy)]
    parents = {root: None for root in roots}
    depth = {root: 0 for root in roots}
    queue = list(roots)
    for node in queue:
        for neighbor in sorted(graph[node]):
            if neighbor not in parents:
                parents[neighbor] = node
                depth[neighbor] = depth[node]+1
                queue.append(neighbor)
    for atom_id in sorted(selected, key=lambda item: (depth[item], item)):
        if atom_id in ring_ids or parents[atom_id] is None:
            continue
        parent = parents[atom_id]
        members = _component(graph, atom_id, parent)
        if parent in members or members & ring_ids:
            raise ValueError("环或交叉连接不能作为刚体支链拍平")
        if members & protected:
            raise ValueError("平面组支链相交，不能互相移动")
        if abs(_dot(_sub(current[atom_id], origin), normal)) > 1e-10:
            _rotate_branch(current, parent, atom_id, members, origin, normal)
    # Only hydrogen on a selected terminal heteroatom is placed in the plane.
    # Other hydrogens retain their spatial relation to their rigid branch.
    for atom_id in sorted(selected):
        if (atom_id in ring_ids or by_id[atom_id]["element"].upper() == "C" or
                len([n for n in graph[atom_id] if n in heavy]) > 1):
            continue
        for hydrogen in sorted(graph[atom_id] - heavy):
            members = _component(graph, hydrogen, atom_id)
            if len(members) != 1 or members & protected:
                raise ValueError("氢支链或平面组相交，不能拍平")
            if abs(_dot(_sub(current[hydrogen], origin), normal)) > 1e-10:
                _rotate_branch(current, atom_id, hydrogen, members, origin, normal)
    for atom_id, xyz in current.items():
        if xyz != positions[atom_id] or str(atom_id) in result:
            result[str(atom_id)] = xyz


def _check_result(positions, bonds, result):
    for xyz in result.values():
        if not all(math.isfinite(v) for v in xyz):
            raise ValueError("拍平后坐标无效")
    for bond in bonds:
        a, b = bond["a"], bond["b"]
        first = result.get(str(a), positions[a])
        second = result.get(str(b), positions[b])
        before = _length(_sub(positions[a], positions[b]))
        after = _length(_sub(first, second))
        if before < 1e-8 or abs(after-before) > 1e-6:
            raise ValueError("拍平改变了化学键长度；请检查覆盖坐标或换一个平面")


def _depiction_points(record, positions, heavy):
    """Return Angstrom-scaled preview coordinates only for a complete depiction."""
    raw = record.get("thumbnail_atom_positions")
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict):
        raise ValueError("二维预览坐标无效")
    points = {}
    for atom_id in heavy:
        xy = raw.get(str(atom_id))
        if (not isinstance(xy, (list, tuple)) or len(xy) != 2 or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                    not math.isfinite(v) for v in xy)):
            raise ValueError("二维预览重原子坐标无效或缺失")
        points[atom_id] = (float(xy[0]), -float(xy[1]))
    if len(set(points.values())) != len(points):
        raise ValueError("二维预览重原子热点重合")
    pixel_lengths, bond_lengths = [], []
    for bond in record["bonds"]:
        a, b = bond["a"], bond["b"]
        if a in heavy and b in heavy:
            pixel = math.dist(points[a], points[b])
            physical = math.dist(positions[a], positions[b])
            if pixel <= 1e-6:
                raise ValueError("二维预览连接热点重合")
            if physical > 1e-6:
                pixel_lengths.append(pixel)
                bond_lengths.append(physical)
    if not pixel_lengths:
        if len(heavy) > 1 and any(bond["a"] in heavy and bond["b"] in heavy
                                  for bond in record["bonds"]):
            raise ValueError("二维预览无法从重原子键确定尺度")
        return None
    scale = median(bond_lengths) / median(pixel_lengths)
    return {atom_id: (xy[0] * scale, xy[1] * scale) for atom_id, xy in points.items()}


def _outside_components(selected, heavy_graph):
    unseen = set(heavy_graph) - selected
    components = []
    while unseen:
        start = min(unseen)
        component = {start}
        unseen.remove(start)
        queue = [start]
        for node in queue:
            for neighbor in sorted(heavy_graph[node] & unseen):
                unseen.remove(neighbor)
                component.add(neighbor)
                queue.append(neighbor)
        edges = sorted((inside, outside) for outside in component
                       for inside in heavy_graph[outside] & selected)
        components.append((component, edges))
    return components


def _shortest_outside_path(graph, component, start, finish):
    queue = deque([start])
    parents = {start: None}
    while queue:
        node = queue.popleft()
        if node == finish:
            path = []
            while node is not None:
                path.append(node)
                node = parents[node]
            return list(reversed(path))
        for neighbor in sorted(graph[node] & component):
            if neighbor not in parents:
                parents[neighbor] = node
                queue.append(neighbor)
    return []


def _close_selected_paths(selected, heavy_graph):
    """Add only the exterior paths needed to leave one anchor per branch."""
    selected = set(selected)
    while True:
        addition = None
        for component, edges in _outside_components(selected, heavy_graph):
            if len(edges) <= 1:
                continue
            paths = [_shortest_outside_path(heavy_graph, component, first[1], second[1])
                     for index, first in enumerate(edges) for second in edges[index + 1:]]
            addition = min(paths, key=lambda path: (len(path), path))
            break
        if addition is None:
            return selected
        selected.update(addition)


def _rotate_vector(vector, source, target):
    """Shortest rigid rotation mapping source direction onto target direction."""
    source_length, target_length = _length(source), _length(target)
    if source_length < 1e-10 or target_length < 1e-10:
        return vector[:]
    first = [v / source_length for v in source]
    second = [v / target_length for v in target]
    cosine = max(-1.0, min(1.0, _dot(first, second)))
    axis = _cross(first, second)
    sine = _length(axis)
    angle_sine = sine
    if sine < 1e-12:
        if cosine > 0:
            return vector[:]
        basis = [1., 0., 0.] if abs(first[0]) < 0.8 else [0., 1., 0.]
        axis = _cross(first, basis)
        sine = _length(axis)
        angle_sine = 0.
    axis = [v / sine for v in axis]
    cross = _cross(axis, vector)
    projection = _dot(axis, vector)
    return [cosine * vector[i] + angle_sine * cross[i] +
            (1. - cosine) * projection * axis[i] for i in range(3)]


def _depiction_basis(normal, plane):
    if plane == "xy":
        return [1., 0., 0.], [0., 1., 0.]
    if plane == "xz":
        return [1., 0., 0.], [0., 0., 1.]
    if plane == "yz":
        return [0., 1., 0.], [0., 0., 1.]
    axis = min(range(3), key=lambda index: abs(normal[index]))
    reference = [float(index == axis) for index in range(3)]
    u = _sub(reference, [_dot(reference, normal) * value for value in normal])
    u = [value / _length(u) for value in u]
    return u, _cross(normal, u)


def _spread_outer_branches(moved, branches, normal, elements, bonds,
                           carried_planes=None):
    """Choose bounded rigid torsions; accept only lower nonbonded crowding.

    Canonical roll frames remove history from the candidate grid, so pressing
    flatten again does not progressively wind a branch around its attachment.
    The selected skeleton, attachment endpoints and branch shape stay fixed.
    """
    if not branches:
        return moved
    bond_lookup = {frozenset((bond["a"], bond["b"])): bond for bond in bonds}
    canonical = {atom_id: xyz[:] for atom_id, xyz in moved.items()}
    rotations = []
    pair_set = set()
    potential_movable = set().union(*(members for _, _, members in branches))
    for parent, child, members in branches:
        bond = bond_lookup[frozenset((parent, child))]
        if bond.get("aromatic") or float(bond.get("order", 1)) != 1:
            continue
        axis = _unit_normal(_sub(moved[child], moved[parent]))
        tangent = None
        # A heavy off-axis member makes a stable roll frame; hydrogens are the
        # fallback for a terminal methyl group.
        ordered = sorted(members, key=lambda item: (elements[item] == "H", item))
        for atom_id in ordered:
            relative = _sub(moved[atom_id], moved[child])
            projected = _sub(relative, [_dot(relative, axis)*v for v in axis])
            if _length(projected) > 1e-8:
                tangent = [v / _length(projected) for v in projected]
                break
        if tangent is None:
            continue
        reference = _sub(normal, [_dot(normal, axis)*v for v in axis])
        if _length(reference) < 1e-8:
            basis = min(range(3), key=lambda index: abs(axis[index]))
            reference = _cross(axis, [float(index == basis) for index in range(3)])
        reference = [v / _length(reference) for v in reference]
        roll = math.atan2(_dot(axis, _cross(tangent, reference)),
                          _dot(tangent, reference))
        pivot = moved[parent]
        for atom_id in members:
            if atom_id == child:
                continue
            rotated = rotate_about_axis(_sub(moved[atom_id], pivot), axis, roll)
            canonical[atom_id] = [pivot[i] + rotated[i] for i in range(3)]
        exterior = set(moved) - members
        # An axial rotation preserves each point's axial and radial distances.
        # Their difference bounds the closest possible approach of any torsion.
        # 2.20 A is the largest sum of the soft radii in collision_score.
        cylindrical = {}
        for atom_id in members | exterior:
            relative = _sub(moved[atom_id], pivot)
            axial = _dot(relative, axis)
            radial = _length(_sub(relative, [axial*v for v in axis]))
            cylindrical[atom_id] = (axial, radial)
        pairs = {(min(a, b), max(a, b)) for a in members for b in exterior
                 if b in potential_movable or
                    math.hypot(cylindrical[a][0] - cylindrical[b][0],
                               cylindrical[a][1] - cylindrical[b][1]) < 2.20}
        if collision_score(moved, elements, bonds, pairs) <= 1e-10:
            # A remote, already clear branch must not inherit an arbitrary
            # canonical roll merely because another branch needed a change.
            for atom_id in members:
                canonical[atom_id] = moved[atom_id][:]
            continue
        pair_set.update(pairs)
        rotations.append((parent, members, axis, roll, sorted(pairs)))
    if not rotations:
        return moved
    candidate = {atom_id: xyz[:] for atom_id, xyz in canonical.items()}
    chosen = []
    for parent, members, axis, roll, pairs in rotations:
        pivot = moved[parent]
        best_angle, best_score = 0., collision_score(candidate, elements, bonds, pairs)
        best = {atom_id: candidate[atom_id][:] for atom_id in members}
        # Twelve torsions are sufficient for branch clearance; each comparison
        # visits only branch/exterior pairs, never a full conformer search.
        for step in range(1, 12):
            angle = step * math.tau / 12
            for atom_id in members:
                relative = _sub(canonical[atom_id], pivot)
                if _length(_cross(relative, axis)) < 1e-12:
                    candidate[atom_id] = canonical[atom_id][:]
                    continue
                rotated = rotate_about_axis(relative, axis, angle)
                candidate[atom_id] = [pivot[i] + rotated[i] for i in range(3)]
            score = collision_score(candidate, elements, bonds, pairs)
            if score < best_score - 1e-10:
                best_angle, best_score = angle, score
                best = {atom_id: candidate[atom_id][:] for atom_id in members}
        candidate.update(best)
        chosen.append((parent, members, axis, roll + best_angle, pairs))
    # Also retain the original roll when this branch contributes no strict
    # improvement with the final positions of its neighbors.
    kept = []
    for parent, members, axis, angle, pairs in chosen:
        reverted = dict(candidate)
        reverted.update({atom_id: moved[atom_id][:] for atom_id in members})
        if collision_score(candidate, elements, bonds, pairs) >= (
                collision_score(reverted, elements, bonds, pairs) - 1e-9):
            candidate = reverted
        else:
            kept.append((parent, members, axis, angle))
    pairs = sorted(pair_set)
    if collision_score(candidate, elements, bonds, pairs) >= (
            collision_score(moved, elements, bonds, pairs) - 1e-9):
        return moved
    if carried_planes:
        for parent, members, axis, angle in kept:
            pivot = moved[parent]
            for frame in carried_planes.values():
                if frame["members"] <= members:
                    rotated = rotate_about_axis(_sub(frame["origin"], pivot), axis, angle)
                    frame["origin"] = [pivot[i] + rotated[i] for i in range(3)]
                    frame["normal"] = _unit_normal(
                        rotate_about_axis(frame["normal"], axis, angle))
    return candidate


def _depiction_flatten(record, positions, heavy, selected, result, depiction,
                       plane="auto", group_plane=None, carried_planes=None):
    """Project the chosen heavy skeleton and rigidly carry each outer branch."""
    current = {atom_id: result.get(str(atom_id), xyz)[:] for atom_id, xyz in positions.items()}
    graph = _graph(positions, record["bonds"])
    heavy_graph = {atom_id: graph[atom_id] & heavy for atom_id in heavy}
    elements = {atom["id"]: atom["element"].upper() for atom in record["atoms"]}
    selected = _close_selected_paths(selected, heavy_graph)
    if carried_planes and any(selected & item["members"]
                              for item in carried_planes.values()):
        raise ValueError("平面组闭环补齐跨入已完成组，目标平面冲突")
    if group_plane is not None:
        plane_origin, normal = group_plane
    elif plane == "auto":
        original_heavy = [positions[item] for item in sorted(heavy)]
        ring = _planar_ring(heavy, positions, record["bonds"])
        plane_origin, normal = (ring[1], ring[2]) if ring else _plane(original_heavy)
    else:
        plane_origin = _center([positions[item] for item in sorted(heavy)])
        normal = {"xy": [0., 0., 1.], "xz": [0., 1., 0.],
                  "yz": [1., 0., 0.]}[plane]
    normal = _unit_normal(normal)
    u, v = _depiction_basis(normal, plane if group_plane is None else "auto")
    ids = sorted(selected)
    image_center = [sum(depiction[item][axis] for item in ids) / len(ids)
                    for axis in range(2)]
    current_center = _center([current[item] for item in ids])
    distance_to_plane = _dot(_sub(current_center, plane_origin), normal)
    target_center = _sub(current_center, [distance_to_plane * value for value in normal])
    target = {}
    for atom_id in ids:
        dx = depiction[atom_id][0] - image_center[0]
        dy = depiction[atom_id][1] - image_center[1]
        target[atom_id] = [target_center[axis] + dx*u[axis] + dy*v[axis]
                           for axis in range(3)]

    moved = {atom_id: xyz[:] for atom_id, xyz in current.items()}
    moved.update(target)
    branches = []
    for component, edges in _outside_components(selected, heavy_graph):
        if not edges:
            continue
        if len(edges) != 1:
            raise ValueError("局部边界存在多个连接点；请扩大所选原子")
        parent, child = edges[0]
        old_vector = _sub(current[child], current[parent])
        old_length = _length(old_vector)
        image_vector = [depiction[child][axis] - depiction[parent][axis]
                        for axis in range(2)]
        image_length = math.hypot(*image_vector)
        if image_length < 1e-9 or old_length < 1e-9:
            raise ValueError("局部连接键长度接近零")
        new_vector = [old_length * (image_vector[0]*u[axis] +
                                    image_vector[1]*v[axis]) / image_length
                      for axis in range(3)]
        members = set(component)
        members.update(hydrogen for atom_id in component
                       for hydrogen in graph[atom_id] - heavy)
        branches.append((parent, child, members))
        if carried_planes:
            for item in carried_planes.values():
                overlap = members & item["members"]
                if not overlap:
                    continue
                if not item["members"] <= members:
                    raise ValueError("平面组被外围支链拆动，目标平面冲突")
                rotated_origin = _rotate_vector(
                    _sub(item["origin"], current[parent]), old_vector, new_vector)
                item["origin"] = [target[parent][axis] + rotated_origin[axis]
                                  for axis in range(3)]
                item["normal"] = _unit_normal(
                    _rotate_vector(item["normal"], old_vector, new_vector))
        for atom_id in members:
            rotated = _rotate_vector(_sub(current[atom_id], current[parent]),
                                     old_vector, new_vector)
            moved[atom_id] = [target[parent][axis] + rotated[axis]
                              for axis in range(3)]

    moved = arrange_hydrogens(record, positions, moved, selected, normal)
    moved = _spread_outer_branches(moved, branches, normal, elements,
                                   record["bonds"], carried_planes)
    if any(not all(math.isfinite(value) for value in xyz) for xyz in moved.values()):
        raise ValueError("拍平后坐标无效")
    if carried_planes:
        for item in carried_planes.values():
            if any(abs(_dot(_sub(moved[atom_id], item["origin"]), item["normal"])) > 1e-6
                   for atom_id in item["members"]):
                raise ValueError("平面组偏离有效目标平面，目标平面冲突")
    return {str(atom_id): xyz for atom_id, xyz in moved.items()}


def _depiction_groups_already_applied(plans, depiction, result, positions, bonds):
    """Recognize complete 2D group layouts after earlier planes were carried."""
    if not all(str(atom_id) in result and
               all(math.isfinite(value) for value in result[str(atom_id)])
               for atom_id in positions):
        return False
    for _component_id, selected, _origin, _normal in plans:
        if len(selected) < 2:
            return False
        ids = sorted(selected)
        for index, a in enumerate(ids):
            for b in ids[index + 1:]:
                if abs(math.dist(result[str(a)], result[str(b)]) -
                       math.dist(depiction[a], depiction[b])) > 1e-5:
                    return False
        for bond in bonds:
            a, b = bond["a"], bond["b"]
            if (a in selected) != (b in selected) and a in positions and b in positions:
                if abs(math.dist(result[str(a)], result[str(b)]) -
                       math.dist(positions[a], positions[b])) > 1e-5:
                    return False
    last_by_component = {component_id: (selected, origin, normal)
                         for component_id, selected, origin, normal in plans}
    return all(abs(_dot(_sub(result[str(atom_id)], origin), normal)) <= 1e-6
               for selected, origin, normal in last_by_component.values()
               for atom_id in selected)


def make_plane_group(record, atom_ids):
    """Describe a plane anchored to selected original heavy-atom positions."""
    by_id, positions, heavy = _record_positions(record)
    selected = _selected_heavy(atom_ids, by_id, heavy)
    points = [positions[atom_id] for atom_id in sorted(selected)]
    origin = _center(points)
    ring = _planar_ring(heavy, positions, record["bonds"])
    ring_selected = sorted(selected & set(ring[0])) if ring else []
    if len(ring_selected) >= 3:
        origin, normal = _plane([positions[i] for i in ring_selected])
    elif len(selected) >= 3:
        _, normal = _plane(points)
    else:
        _, normal = (ring[1], ring[2]) if ring else _plane([positions[i] for i in sorted(heavy)])
    return {"atom_ids": sorted(selected), "origin": origin, "normal": _unit_normal(normal)}


def apply_plane_groups(record, groups, existing_overrides=None):
    """Apply disjoint heavy-atom plane groups to current display positions."""
    if not isinstance(groups, dict):
        raise ValueError("平面组必须是字典")
    by_id, positions, heavy = _record_positions(record)
    result = _copy_overrides(existing_overrides, by_id)
    assigned = set()
    parsed = []
    for group_id in sorted(groups, key=str):
        group = groups[group_id]
        if not isinstance(group_id, str) or not group_id.isascii() or not group_id.isdigit():
            raise ValueError("平面组 id 必须是数字字符串")
        if not isinstance(group, dict) or "atom_ids" not in group:
            raise ValueError("平面组数据无效")
        members = list(group["atom_ids"])
        selected = _selected_heavy(members, by_id, heavy)
        if len(members) != len(selected):
            raise ValueError("平面组只能包含不重复的重原子")
        if selected & assigned:
            raise ValueError("重原子不能属于多个平面组")
        assigned.update(selected)
        origin = group.get("origin")
        if (not isinstance(origin, (list, tuple)) or len(origin) != 3 or
                any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in origin)):
            raise ValueError("平面原点必须是有限的三元组")
        parsed.append((selected, [float(v) for v in origin], _unit_normal(group.get("normal"))))
    if not parsed:
        return result
    depiction = _depiction_points(record, positions, heavy)
    if depiction is not None:
        graph = _graph(positions, record["bonds"])
        heavy_graph = {atom_id: graph[atom_id] & heavy for atom_id in heavy}
        component_of = {}
        for atom_id in sorted(heavy):
            if atom_id not in component_of:
                members = _component(heavy_graph, atom_id, -1)
                for member in members:
                    component_of[member] = atom_id
        plans = []
        for selected, origin, normal in parsed:
            for component_id in sorted({component_of[item] for item in selected}):
                relevant = selected & {item for item in heavy
                                       if component_of[item] == component_id}
                matching = next((plan for plan in plans
                                 if plan[0] == component_id and
                                 abs(abs(_dot(plan[3], normal)) - 1.) <= 1e-5 and
                                 abs(_dot(_sub(origin, plan[2]), plan[3])) <= 1e-4), None)
                if matching is None:
                    plans.append([component_id, set(relevant), origin, normal])
                else:
                    matching[1].update(relevant)
        # Closed selections may also intersect at unassigned path atoms.
        closed_plans = [(component_id, _close_selected_paths(selected, heavy_graph),
                         origin, normal)
                        for component_id, selected, origin, normal in plans]
        for index, (component_id, closed, _origin, _normal) in enumerate(closed_plans):
            if any(closed & other[1] for other in closed_plans[index + 1:]
                   if other[0] == component_id):
                raise ValueError("平面组闭环补齐跨入另一目标平面，目标平面冲突")
        if _depiction_groups_already_applied(
                closed_plans, depiction, result, positions, record["bonds"]):
            return result

        def apply_from(start):
            effective_planes = {}
            applied = start
            for index, (_component_id, selected, origin, normal) in enumerate(closed_plans):
                applied = _depiction_flatten(
                    record, positions, heavy, selected, applied, depiction,
                    group_plane=(origin, normal), carried_planes=effective_planes)
                effective_planes[index] = {
                    "members": set(selected), "origin": origin[:], "normal": normal[:],
                }
            for item in effective_planes.values():
                if any(abs(_dot(_sub(applied[str(atom_id)], item["origin"]),
                                item["normal"])) > 1e-6
                       for atom_id in item["members"]):
                    raise ValueError("平面组偏离有效目标平面，目标平面冲突")
            return applied

        canonical = apply_from({})
        if (all(str(atom_id) in result for atom_id in positions) and
                all(math.dist(result[str(atom_id)], canonical[str(atom_id)]) <= 1e-7
                    for atom_id in positions)):
            return result
        return canonical if not result else apply_from(result)
    graph = _graph(positions, record["bonds"])
    ring = _planar_ring(heavy, positions, record["bonds"])
    cyclic = _cyclic_heavy(heavy, graph)
    if cyclic and not ring:
        raise ValueError("非平面环不能在保持键长时拍平")
    ring_ids = set(ring[0]) if ring else set()
    for selected, origin, normal in parsed:
        if selected & (cyclic - ring_ids):
            raise ValueError("环连接结构不能作为刚体支链拍平")
        if any(abs(_dot(_sub(positions[item], origin), normal)) > 0.15
               for item in selected & ring_ids):
            raise ValueError("固定芳环不在目标平面，不能保持键长拍平")
        # A later group may not reorient any previously assigned member.
        protected = assigned - selected
        _rigid_flatten(positions, record["bonds"], by_id, heavy, selected, origin, normal,
                       result, ring_ids, protected)
    _check_result(positions, record["bonds"], result)
    return result


def flatten_overrides(record, existing_overrides=None, atom_ids=None, plane="auto"):
    """Flatten against complete 2D depictions, with a rigid legacy fallback.

    Returns a fresh ``dict[str, list[float]]`` of absolute display coordinates.
    The plane is always calculated from original record coordinates, so a local
    operation does not tilt a stable ring in response to earlier overrides.
    """
    if plane not in ("auto", "xy", "xz", "yz"):
        raise ValueError("未知平面；请选择 auto、xy、xz 或 yz")
    by_id, positions, heavy = _record_positions(record)
    if atom_ids is None:
        selected = heavy
    else:
        selected = _selected_heavy(atom_ids, by_id, heavy)

    result = _copy_overrides(existing_overrides, by_id)
    depiction = _depiction_points(record, positions, heavy)
    if depiction is not None:
        return _depiction_flatten(record, positions, heavy, selected, result,
                                  depiction, plane)

    original_heavy = [positions[item] for item in sorted(heavy)]
    ring = _planar_ring(heavy, positions, record["bonds"])
    if plane == "auto":
        origin, normal = (ring[1], ring[2]) if ring else _plane(original_heavy)
    else:
        origin = _center(original_heavy)
        normal = {"xy": [0.0, 0.0, 1.0], "xz": [0.0, 1.0, 0.0],
                  "yz": [1.0, 0.0, 0.0]}[plane]

    graph = _graph(positions, record["bonds"])
    cyclic = _cyclic_heavy(heavy, graph)
    if cyclic and not ring:
        raise ValueError("非平面环不能在保持键长时拍平")
    ring_ids = set(ring[0]) if ring else set()
    if selected & (cyclic - ring_ids):
        raise ValueError("环连接结构不能作为刚体支链拍平")
    if any(abs(_dot(_sub(positions[item], origin), normal)) > 0.15
           for item in selected & ring_ids):
        raise ValueError("固定芳环不在目标平面，不能保持键长拍平")
    _rigid_flatten(positions, record["bonds"], by_id, heavy, selected, origin, normal,
                   result, ring_ids)
    if atom_ids is None:
        for atom_id in positions:
            result.setdefault(str(atom_id), positions[atom_id][:])
    _check_result(positions, record["bonds"], result)
    return result
