'''
*** CONTAINS MODIFIED CODE FROM NETWORKX ***

Copyright (c) 2004-2025, NetworkX Developers
Aric Hagberg <hagberg@lanl.gov>
Dan Schult <dschult@colgate.edu>
Pieter Swart <swart@lanl.gov>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

  * Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

  * Redistributions in binary form must reproduce the above
    copyright notice, this list of conditions and the following
    disclaimer in the documentation and/or other materials provided
    with the distribution.

  * Neither the name of the NetworkX Developers nor the names of its
    contributors may be used to endorse or promote products derived
    from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
'''
import math
import networkx as nx
from osmnx import convert
from heapq import heappop, heappush
from itertools import count
from networkx.algorithms.shortest_paths.weighted import _weight_function

def astar(
    G,
    source,
    target,
    heuristic=None,
    weight="weight",
    ignore_nodes=None,
    ignore_edges=None,
):
    """
    Generic A* Shortest Path Algorithm.

    Parameters
    ----------
    G : NetworkX Graph

    source : starting node

    target : destination node

    heuristic : function
        A function that accepts (G, node, target)
        and returns the heuristic estimate.

    weight : edge attribute name

    ignore_nodes : optional set of nodes to ignore

    ignore_edges : optional set of edges to ignore

    Returns
    -------
    (distance, path)
    """

    if source not in G:
        raise nx.NodeNotFound(f"Node {source} not in graph")
    if target not in G:
        raise nx.NodeNotFound(f"Node {target} not in graph")
    if source == target:
        return 0, [source]

    ignore_nodes = set(ignore_nodes or [])
    ignore_edges = set(ignore_edges or [])
    heuristic = heuristic or zero_heuristic

    if source in ignore_nodes or target in ignore_nodes:
        raise nx.NetworkXNoPath(f"No path between {source} and {target}.")

    # Priority queue values are (f_score, tie_breaker, g_score, node).
    open_set = []
    counter = count()
    adjacency = G._adj

    heappush(
        open_set,
        (
            heuristic(G, source, target),
            next(counter),
            0,
            source,
        )
    )

    came_from = {}

    g_score = {
        source: 0
    }

    visited = set()

    while open_set:

        _, _, current_g, current = heappop(open_set)

        if current == target:

            path = [current]

            while current in came_from:
                current = came_from[current]
                path.append(current)

            path.reverse()

            return current_g, path

        if current in visited:
            continue

        visited.add(current)

        for neighbor, edge_data in adjacency[current].items():

            if neighbor in ignore_nodes:
                continue

            edge_weight = _edge_weight(
                G,
                current,
                neighbor,
                weight,
                ignore_edges,
                edge_data,
            )

            if edge_weight is None:
                continue

            tentative_g = current_g + edge_weight

            if (
                neighbor not in g_score
                or tentative_g < g_score[neighbor]
            ):

                g_score[neighbor] = tentative_g

                came_from[neighbor] = current

                f_score = tentative_g + heuristic(
                    G,
                    neighbor,
                    target,
                )

                heappush(
                    open_set,
                    (
                        f_score,
                        next(counter),
                        tentative_g,
                        neighbor,
                    )
                )

    raise nx.NetworkXNoPath(
        f"No path between {source} and {target}"
    )


def _edge_is_ignored(G, u, v, key, ignore_edges):
    if (u, v) in ignore_edges or (key is not None and (u, v, key) in ignore_edges):
        return True

    if not G.is_directed():
        return (
            (v, u) in ignore_edges
            or (key is not None and (v, u, key) in ignore_edges)
        )

    return False


def _edge_weight(G, u, v, weight, ignore_edges=None, data=None):
    """Return the best usable edge weight between two nodes."""
    ignore_edges = ignore_edges or set()
    if data is None:
        data = G.get_edge_data(u, v)

    if data is None:
        return None

    if G.is_multigraph():
        best_weight = None
        for key, edge_data in data.items():
            if _edge_is_ignored(G, u, v, key, ignore_edges):
                continue
            if callable(weight):
                value = weight(u, v, edge_data)
            else:
                value = edge_data.get(weight, 1)
            if value is not None and (best_weight is None or value < best_weight):
                best_weight = value
        return best_weight

    if _edge_is_ignored(G, u, v, None, ignore_edges):
        return None
    if callable(weight):
        return weight(u, v, data)
    return data.get(weight, 1)


def path_weight(G, path, weight="weight"):
    total = 0

    for u, v in zip(path, path[1:]):
        edge_weight = _edge_weight(G, u, v, weight)
        if edge_weight is None:
            raise nx.NetworkXNoPath(f"No edge between {u} and {v}.")
        total += edge_weight

    return total


def _node_lat_lon(G, node):
    data = G.nodes[node]

    if "lat" in data and "lon" in data:
        return data["lat"], data["lon"]
    if "y" in data and "x" in data:
        return data["y"], data["x"]

    raise KeyError(
        f"Node {node} needs either lat/lon or y/x coordinates for Haversine."
    )


# ============================================================
# Haversine Heuristic
# ============================================================

EARTH_RADIUS = 6371000  # meters
DEFAULT_HEURISTIC_SPEED_MPS = 3.89
_HEURISTIC_SCALE_CACHE = {}
_NODE_RAD_CACHE = {}


def _get_node_rad(G, node):
    if node in _NODE_RAD_CACHE:
        return _NODE_RAD_CACHE[node]
    try:
        lat, lon = _node_lat_lon(G, node)
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        cos_lat = math.cos(lat_rad)
        val = (lat_rad, lon_rad, cos_lat)
        _NODE_RAD_CACHE[node] = val
        return val
    except KeyError:
        raise KeyError(
            f"Node {node} needs either lat/lon or y/x coordinates for Haversine."
        )


def haversine_heuristic(G, node, target):
    try:
        lat1, lon1, cos_lat1 = _get_node_rad(G, node)
        lat2, lon2, cos_lat2 = _get_node_rad(G, target)
    except KeyError:
        raise KeyError("Coordinates not found for Haversine heuristic calculation.")

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + cos_lat1
        * cos_lat2
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS * c


def _haversine_distance(lat1, lon1, lat2, lon2):
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS * c


def make_haversine_heuristic(G, weight="weight"):
    """
    Build an admissible Haversine heuristic in the same unit as edge weights.

    Raw Haversine returns meters. A* needs the heuristic in the same unit as
    edge weights, so this scales distance by the smallest observed edge cost
    per meter. The scale is cached per graph size to avoid repeat scans.
    """
    cost_per_meter = _get_haversine_cost_per_meter(G, weight)

    def scaled_haversine_heuristic(graph, node, target):
        try:
            return haversine_heuristic(graph, node, target) * cost_per_meter
        except KeyError:
            return 0

    return scaled_haversine_heuristic


def make_target_haversine_heuristic(G, target, weight="weight"):
    """Build a faster Haversine heuristic for one fixed target node."""
    cost_per_meter = _get_haversine_cost_per_meter(G, weight)

    if cost_per_meter <= 0:
        return zero_heuristic

    try:
        target_lat, target_lon, target_cos_lat = _get_node_rad(G, target)
    except KeyError:
        return zero_heuristic

    def target_haversine_heuristic(graph, node, goal):
        try:
            lat, lon, cos_lat = _get_node_rad(graph, node)
        except KeyError:
            return 0

        dlat = target_lat - lat
        dlon = target_lon - lon

        a = (
            math.sin(dlat / 2) ** 2
            + cos_lat
            * target_cos_lat
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return (EARTH_RADIUS * c) * cost_per_meter

    return target_haversine_heuristic


def _get_haversine_cost_per_meter(G, weight="weight"):
    cache_key = (id(G), G.number_of_nodes(), G.number_of_edges(), weight)
    if cache_key in _HEURISTIC_SCALE_CACHE:
        return _HEURISTIC_SCALE_CACHE[cache_key]

    min_cost_per_meter = math.inf

    if G.is_multigraph():
        edge_iter = G.edges(data=True, keys=True)
        for u, v, _, data in edge_iter:
            min_cost_per_meter = _update_min_cost_per_meter(
                G,
                u,
                v,
                data,
                weight,
                min_cost_per_meter,
            )
    else:
        for u, v, data in G.edges(data=True):
            min_cost_per_meter = _update_min_cost_per_meter(
                G,
                u,
                v,
                data,
                weight,
                min_cost_per_meter,
            )

    if min_cost_per_meter == math.inf or min_cost_per_meter <= 0:
        min_cost_per_meter = 1 / DEFAULT_HEURISTIC_SPEED_MPS

    _HEURISTIC_SCALE_CACHE[cache_key] = min_cost_per_meter
    return min_cost_per_meter

# Finds the fastest mode speed
def _update_min_cost_per_meter(G, u, v, edge_data, weight, current_min):
    if callable(weight):
        edge_weight = weight(u, v, edge_data)
    else:
        edge_weight = edge_data.get(weight, 1)

    if edge_weight is None:
        return current_min

    try:
        lat1, lon1 = _node_lat_lon(G, u)
        lat2, lon2 = _node_lat_lon(G, v)
    except KeyError:
        return current_min

    distance = _haversine_distance(lat1, lon1, lat2, lon2)
    if distance <= 0:
        return current_min

    return min(current_min, edge_weight / distance)


# ============================================================
# Zero Heuristic
# (Makes A* behave exactly like Dijkstra)
# ============================================================

def zero_heuristic(G, node, target):
    return 0


def yens(
    G,
    source,
    target,
    k,
    weight="weight",
    heuristic=None,
):
    """
    Yield up to k shortest simple paths using Yen's algorithm over A*.

    A* finds the first shortest path and each later spur path. Yen's layer
    keeps those A* searches loopless by temporarily ignoring root-path nodes
    and edges already used by accepted paths.
    """
    if k <= 0:
        return

    heuristic = heuristic or make_target_haversine_heuristic(G, target, weight)

    _, first_path = astar(
        G,
        source,
        target,
        heuristic=heuristic,
        weight=weight,
    )

    accepted_paths = [first_path]
    accepted_keys = {tuple(first_path)}
    candidate_paths = []
    candidate_keys = set()
    counter = count()

    yield first_path

    for path_index in range(1, k):
        previous_path = accepted_paths[path_index - 1]
        prefix_costs = [0]

        for u, v in zip(previous_path, previous_path[1:]):
            edge_weight = _edge_weight(G, u, v, weight)
            if edge_weight is None:
                raise nx.NetworkXNoPath(f"No edge between {u} and {v}.")
            prefix_costs.append(prefix_costs[-1] + edge_weight)

        for spur_index in range(len(previous_path) - 1):
            spur_node = previous_path[spur_index]
            root_path = previous_path[: spur_index + 1]
            root_cost = prefix_costs[spur_index]
            ignored_nodes = set(root_path[:-1])
            ignored_edges = set()

            for path in accepted_paths:
                if (
                    len(path) > spur_index + 1
                    and path[: spur_index + 1] == root_path
                ):
                    ignored_edges.add((path[spur_index], path[spur_index + 1]))

            try:
                spur_cost, spur_path = astar(
                    G,
                    spur_node,
                    target,
                    heuristic=heuristic,
                    weight=weight,
                    ignore_nodes=ignored_nodes,
                    ignore_edges=ignored_edges,
                )
            except nx.NetworkXNoPath:
                continue

            candidate = root_path[:-1] + spur_path
            candidate_key = tuple(candidate)

            if candidate_key in accepted_keys or candidate_key in candidate_keys:
                continue

            candidate_keys.add(candidate_key)
            heappush(
                candidate_paths,
                (root_cost + spur_cost, next(counter), candidate),
            )

        if not candidate_paths:
            break

        _, _, next_path = heappop(candidate_paths)
        candidate_keys.remove(tuple(next_path))
        accepted_paths.append(next_path)
        accepted_keys.add(tuple(next_path))
        yield next_path


def get_k_shortest_paths(
    G,
    source,
    target,
    k,
    weight="weight",
    heuristic=None,
):
    """Compatibility wrapper used by main.py for the A* + Yen hybrid option."""
    if k <= 0:
        return

    if G.is_multigraph():
        G = convert.to_digraph(G, weight=weight)

    heuristic = heuristic or make_target_haversine_heuristic(G, target, weight)
    yield from yens(
        G,
        source,
        target,
        k,
        weight=weight,
        heuristic=heuristic,
    )