from fastapi import FastAPI, HTTPException
import networkx as nx
import time
from contextlib import contextmanager
import osmnx as ox
import geopandas as gpd
import numpy as np
import os
import json
import math
import requests
from shapely.ops import linemerge
import copy
import traceback
from shapely.geometry import shape, LineString
from func import getNearestNodeId, getFare, haversine
from algo import get_k_shortest_paths
from fastapi.middleware.cors import CORSMiddleware
# --------------- INITIALIZE GRAPH --------------- #


@contextmanager
def perfTimer(action=""):
    start = time.perf_counter()
    yield
    end = time.perf_counter()
    print(f"Elapsed time to {action}: {round(end - start, 2)}s", flush=True)

with perfTimer("read nodes and edges of mabalacat+angeles City"):
    nodes = gpd.read_file("graph/transit_graph/walking_graph/mabalacatAngelesWalking_nodes.geojson")
    edges = gpd.read_file("graph/transit_graph/walking_graph/mabalacatAngelesWalking_edges.geojson")

with perfTimer("Fix index of nodes and edges"):
    nodes = nodes.set_index("osmid")
    edges = edges.set_index(["u", "v", "key"])

with perfTimer("convert np arrays to lists"):
    for attr in edges.columns:
        new_values = []

        for val in edges[attr]:
            if isinstance(val, np.ndarray):
                new_values.append(val.tolist())
            else:
                new_values.append(val)

        edges[attr] = new_values

with perfTimer("initialize MultiDiGraph"):
    G = ox.graph_from_gdfs(nodes, edges)

with perfTimer("deepcopy MultiDiGraph to walking graph"):
    walkingG = copy.deepcopy(G)
# -------------------------------------------------- #
# --------- INITIALIZE SIMPLIFIED GRAPH ------------ #

with perfTimer("read nodes and edges of minimized transit graph"):
    nodes = gpd.read_file("graph/transit_graph/simplified_graph/simplifiedGraph_nodes.geojson")
    edges = gpd.read_file("graph/transit_graph/simplified_graph/simplifiedGraph_edges.geojson")

with perfTimer("Fix index of nodes and edges"):
    nodes = nodes.set_index("osmid")
    edges = edges.set_index(["u", "v", "key"])

    with perfTimer("convert np arrays to lists"):
        for attr in edges.columns:
            new_values = []

            for val in edges[attr]:
                if isinstance(val, np.ndarray):
                    new_values.append(val.tolist())
                else:
                    new_values.append(val)

            edges[attr] = new_values

with perfTimer("initialize minimized MultiDiGraph"):

    minimizedG = ox.graph_from_gdfs(nodes, edges)


# -------------------------------------------------- #
# ------------------ ADD SUBGRAPHS ----------------- #
with perfTimer("add tricycle subgraphs"):
    relativePath = "graph/transit_graph/trike_routes"
    subgraphG = nx.MultiDiGraph()
    coord_to_node_subg = {}
    coord_to_node_terminal = {}

    for route in os.listdir(relativePath):

        for file in os.listdir(f"{relativePath}/{route}"):

            if file.endswith('_nodes.geojson'):
                with open(f"{relativePath}/{route}/{file}") as f:
                    nodesJson = json.load(f)

                for feature in nodesJson["features"]:
                    props = feature["properties"].copy()
                    geom = feature["geometry"]
                    node_id = props["osmid"]
                    lon, lat = geom["coordinates"]
                    props["x"] = lon
                    props["y"] = lat

                    if feature['properties']['mode']['details']['terminal'] != False:
                        coord_to_node_terminal[(lon, lat)] = feature
                    coord_to_node_subg[(lon, lat)] = feature
                    subgraphG.add_node(node_id, **props)
                    G.add_node(node_id, **props)

            elif file.endswith('_edges.geojson'):
                with open(f"{relativePath}/{route}/{file}") as f:
                    edgesJson = json.load(f)

                for feature in edgesJson["features"]:
                    props = feature["properties"]
                    geom = feature["geometry"]

                    u = props.pop("u")
                    v = props.pop("v")

                    subgraphG.add_edge(
                        u,
                        v,
                        geometry=shape(geom),
                        **props
                    )
                    G.add_edge(
                        u,
                        v,
                        geometry=shape(geom),
                        **props
                    )
            else:
                print("Throw not correct format")
# ------------------ ADD SUBGRAPHS ----------------- #
with perfTimer("add jeep routes"):
    relativePath = "graph/transit_graph/jeep_routes"

    for route in os.listdir(relativePath):

        for file in os.listdir(f"{relativePath}/{route}"):

            if file.endswith('_nodes.geojson'):
                with open(f"{relativePath}/{route}/{file}") as f:
                    nodesJson = json.load(f)

                for feature in nodesJson["features"]:
                    props = feature["properties"].copy()
                    geom = feature["geometry"]
                    node_id = props["osmid"]
                    lon, lat = geom["coordinates"]
                    props["x"] = lon
                    props["y"] = lat

                    G.add_node(node_id, **props)

            elif file.endswith('_edges.geojson'):
                with open(f"{relativePath}/{route}/{file}") as f:
                    edgesJson = json.load(f)

                for feature in edgesJson["features"]:
                    props = feature["properties"]
                    geom = feature["geometry"]

                    u = props.pop("u")
                    v = props.pop("v")

                    G.add_edge(
                        u,
                        v,
                        geometry=shape(geom),
                        **props
                    )
            else:
                print("Throw not correct format")
# -------------------------------------------------- #
# ------ GET UNIQUE NODE AND EDGE ID FUNCTION ------ #
nodeIdIndex = 0
edgeIdIndex = 0

def max_osmid(base_path, suffix):
    max_id = 0
    for route in os.listdir(base_path):
        for file in os.listdir(f"{base_path}/{route}"):
            if file.endswith(suffix):
                with open(f"{base_path}/{route}/{file}") as f:
                    data = json.load(f)
                ids = [int(feat['properties']['osmid']) for feat in data['features']]
                if ids:
                    max_id = max(max_id, max(ids))
    return max_id

edgeIdIndex = max(
    max_osmid("graph/transit_graph/trike_routes", "edges.geojson"),
    max_osmid("graph/transit_graph/jeep_routes", "edges.geojson")
)

nodeIdIndex = max(
    max_osmid("graph/transit_graph/trike_routes", "nodes.geojson"),
    max_osmid("graph/transit_graph/jeep_routes", "nodes.geojson")
)

def getNodeId():
    global edgeIdIndex
    current = edgeIdIndex
    edgeIdIndex +=1
    return current

def getEdgeId():
    global nodeIdIndex
    current = nodeIdIndex
    nodeIdIndex +=1
    return current
# -------------------------------------------------- #
# -------------- ADD EDGE SEGMENT ------------------ #
def collapseBySegment(G, targetG, path):
    '''
    Iterates through a shortest path and collapses each contiguous same-mode segment into its own edge,
    preserving mode transitions (e.g. trike -> walk -> jeep) instead of losing them
    in a single flattened edge, then adds to a targetG which will contain the collapsed segments

    Parameters
    ----------
    G
        Source graph containing full node/edge data

    targetG
        Graph to add the collapsed nodes/edges into

    path
        List of node ids representing the path to collapse

    Returns
    ----------
    None (mutates targetG directly)
    '''

    segments = []
    currentSegment = [path[0]]
    currentNodeMode = G.nodes[path[0]]['mode']
    currentMode = currentNodeMode['type']
    currentName = currentNodeMode['details']['name'] if currentMode != 'walk' else 'on foot'

    for node in path[1:]:
        nodeModeData = G.nodes[node]['mode']
        nodeMode = nodeModeData['type']
        nodeName = nodeModeData['details']['name'] if nodeMode != 'walk' else 'on foot'

        if nodeMode == currentMode:
            currentSegment.append(node)
        else:
            segments.append((currentSegment, currentMode, currentName))
            currentSegment = [currentSegment[-1], node]
            currentMode = nodeMode
            currentName = nodeName

    segments.append((currentSegment, currentMode, currentName))

    collapsedEdges = []

    for segmentNodes, mode, name in segments:
        # Check if list of segment nodes is not a singular node, which means no mode edge
        if len(segmentNodes) < 2:
            continue  

        # Increment tracker for weight, length, and line geomtry
        totalWeight = 0; totalLength = 0; geometries = []

        # Loop through u v pairs of a segment
        for u, v in zip(segmentNodes, segmentNodes[1:]):
            edgeAttrs = G[u][v][0]
            totalWeight += edgeAttrs.get('weight', 0)
            totalLength += edgeAttrs.get('length', 0)

            if 'geometry' in edgeAttrs:
                geometries.append(edgeAttrs['geometry'])
            else:
                geometries.append(shape({
                    "type": "LineString",
                    "coordinates": [
                        [G.nodes[u]['x'], G.nodes[u]['y']],
                        [G.nodes[v]['x'], G.nodes[v]['y']]
                    ]
                }))

        # Something about geometry
        allCoords = []
        for geomPart in geometries:
            coords = list(geomPart.coords)
            if allCoords and allCoords[-1] == coords[0]:
                coords = coords[1:]
            allCoords.extend(coords)

        # if s:
        #     print(allCoords)

        combinedGeometry = LineString(allCoords)

        u, v = segmentNodes[0], segmentNodes[-1]



        # Only add the two boundary nodes actually used by this edge
        for osmid in (u, v):
            attrs = G.nodes[osmid].copy()
            targetG.add_node(osmid, **attrs)

            
        targetG.add_edge(
            u, v,
            osmid=str(getEdgeId()),
            weight=totalWeight,
            length=totalLength,
            geometry=combinedGeometry,
            original_osmids=segmentNodes,
            mode={"type": mode, "details": {"name": name}}
        )
# -------------------------------------------------- #
# ---------------- MODE SPEEDS (km/h) -------------- #
JEEP_SPEED = 14.0
TRIKE_SPEED = 23.0
WALK_SPEED = 4.5
# ------------------ ADD COLOR HASH ---------------- #
with open(f"graph_config/color.json") as f:
    colors = json.load(f)
# -------------------------------------------------- #

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:8080'],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"]
)


@app.get("/")
def root():
    return {"Key": "Value"}

@app.get("/test/{someVar}")
def test(someVar: str):
    return {"Key": someVar}

@app.get("/param")
def param(paramOne: str = "DefaultOne", paramTwo: str = "DefaultTwo"):
    return {"Key1": paramOne, "Key2": paramTwo}

@app.get("/flutterTest")
def flutterTest():
    return {"key": "Hello from FastAPI!"}


# ------------ ADD ROUTE TOGGLE API------------------- #
@app.get("/jeep_routes")
def jeep_routes():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    routes_path = os.path.join(
        base_dir,
        "graph",
        "transit_graph",
        "jeep_routes"
    )

    route_list = []

    for route_name in os.listdir(routes_path):
        route_dir = os.path.join(routes_path, route_name)
        if not os.path.isdir(route_dir):
            continue
        edges_file = os.path.join(route_dir, f"{route_name}_edges.geojson")
        if not os.path.exists(edges_file):
            continue
        with open(edges_file, "r") as file:
            edges_geojson = json.load(file)
        route_list.append({
            "id": route_name,
            "name": route_name,
            "color": colors.get(route_name, "#1e8847"),
            "geojson": edges_geojson
        })
    return {"routes": route_list}

@app.get("/trike_terminals_list")
def jeep_routes():
    trikeGraphsDir = r"graph/transit_graph/trike_routes"

    terminalList = []

    for subgraph in os.listdir(trikeGraphsDir):
        with open(f"{trikeGraphsDir}/{subgraph}/{subgraph}_nodes.geojson", "r") as file:
            nodesGeojson = json.load(file)
        for node in nodesGeojson['features']:
            if node['properties']['mode']['details']['terminal'] != False:
                terminalList.append({"terminalName": node['properties']['mode']['details']['terminal'], "coordinates": {"lat": node['properties']['y'], "long": node['properties']['x']}})

    return {"terminalList": terminalList}
    
@app.get("/k_shortest_paths")
def kShortestPaths(src: str, dest: str, algo:str='astar', traffic:bool=False, debug:bool=False):
    '''
    Returns an object of k-shortest paths calculated by shortest path and k-shortest algorithm which contains the separate
    routes to traverse including the path of the mode in order.

    --- EXAMPLE RESULT ---
    {
        routes: 
            result-1: {
                0: {
                    'mode': {
                        'type': 'walk',
                        'details: {
                            'name': 'On foot',
                            'color': '#2005ed'
                        }
                    },
                    'geometry': [
                        [120.58758878271912, 15.14365473416789],
                        [120.58833604642595, 15.1434826439334]
                    ],
                    'traffic': {
                        expectedDuration: 32,
                        actualDuration: 32,
                    }
                },
                1: {
                    'mode': {
                        'type': 'jeep',
                        'details: {
                            'name': 'route-1',
                            'color': '#1d7021'
                        }
                    },
                    'geometry': [
                        [120.58833604642595, 15.1434826439334],
                        [120.58791499937249, 15.14178736453769],
                        [120.58745810400315, 15.139206114741604]
                    ],
                    'traffic': {
                        expectedDuration: 352,
                        actualDuration: 471,
                    }
                },
                2: {
                    'mode': {
                        'type': 'walk',
                        'details: {
                            'name': 'On foot',
                            'color': '#2005ed'
                        }
                    },
                    'geometry': [
                        [120.58745810400315, 15.139206114741604],
                        [120.58704485986307, 15.139215965542231],
                        [120.58680435135506, 15.138876276435527]
                    ],
                    'traffic': {
                        expectedDuration: 85,
                        actualDuration: 85,
                    }
                }
            },
            result-2: {
                0: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': [], 'traffic': {}},
                1: {'mode': {'type': 'walk', 'details': {'name': 'route-2', 'color': '#a11ea6'}}, 'geometry': [], 'traffic': {}},
                2: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': [], 'traffic': {}},
                3: {'mode': {'type': 'walk', 'details': {'name': 'route-3', 'color': '#f0cf13'}}, 'geometry': [], 'traffic': {}},
                4: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': [], 'traffic': {}}
            },
            result-3: {
                0: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': [], 'traffic': {}},
                1: {'mode': {'type': 'walk', 'details': {'name': 'route-4', 'color': '#7c4dc4'}}, 'geometry': [], 'traffic': {}},
                2: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': [], 'traffic': {}},
                3: {'mode': {'type': 'walk', 'details': {'name': 'toda-1', 'color': '#ba1c59'}}, 'geometry': [], 'traffic': {}},
                4: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': [], 'traffic': {}}
            }
    }
    In the example above, a calculated "result-x" would contain a list of routes or modes a person would have to traverse through from
    a source to a destination. Each list element inside result-x represents a modal route that a person has to use in going to 
    their destination.
    -------------------
    
    Parameters
    ----------
    src
        A string literal containing latitude and longitude values for source coordinates separated by comma

    dest
        A string literal containing latitude and longitude values for destination coordinates separated by comma
    Returns
    ----------
    dict
    '''
    try:
        # Splits source and destination arguments from API link into separate dicts of coordinates
        pair = {
            'source': {'lat': float(src.split(',')[0]), 'long': float(src.split(',')[1])},
            'destination': {'lat': float(dest.split(',')[0]), 'long': float(dest.split(',')[1])},
        }

        
        print(f"src lat-y,long-x: {pair['source']['lat']},{pair['source']['long']}")
        print(f"dest lat-y,long-x: { pair['destination']['lat']},{pair['destination']['long']}")

        srcNode = getNearestNodeId(walkingG, pair['source']['lat'], pair['source']['long'])
        destNode = getNearestNodeId(walkingG, pair['destination']['lat'], pair['destination']['long'])

        node_data = G.nodes[srcNode]
        minimizedG.add_node(srcNode, **node_data)

        node_data = G.nodes[destNode]
        minimizedG.add_node(destNode, **node_data)

        # Dictionary of x,y and nodeid pairs
        coord_to_walking_node = {
            (data['x'], data['y']): node
            for node, data in walkingG.nodes(data=True)
        }

        with perfTimer("add walking path from source to dest"):
            # ADD WALKING PATH FROM SOURCE NODE TO DEST NODE
            src_to_dest_dist, src_to_dest_path = nx.single_source_dijkstra(walkingG, source=srcNode, target=destNode, weight='weight')

            # Combine every node/edge of the walking path into a single collapsed edge
            totalWeight = 0; totalLength = 0; geometries = []; originalOsmids = []

            for u, v in zip(src_to_dest_path, src_to_dest_path[1:]):
                edgeAttrs = G[u][v][0]

                totalWeight += edgeAttrs.get('weight', 0)
                totalLength += edgeAttrs.get('length', 0)
                originalOsmids.append(u)

                if 'geometry' in edgeAttrs:
                    geometries.append(edgeAttrs['geometry'])
                else:
                    geometries.append(shape({
                        "type": "LineString",
                        "coordinates": [
                            [G.nodes[u]['x'], G.nodes[u]['y']],
                            [G.nodes[v]['x'], G.nodes[v]['y']]
                        ]
                    }))

            # Add last node's osmid, since the loop above only appended u's
            originalOsmids.append(src_to_dest_path[-1])

            combinedGeometry = linemerge(geometries)

            # Ensures source and dest nodes exist in minimizedG
            for ogId in (srcNode, destNode):
                attrs = G.nodes[ogId].copy()
                minimizedG.add_node(ogId, **attrs)

            # Adds a single collapsed edge from srcNode straight to destNode,
            # carrying combined weight, length, geometry, and the full list of
            # original osmids that made up the walking path
            minimizedG.add_edge(
                srcNode,
                destNode,
                key=0,
                osmid=str(getEdgeId()),
                weight=totalWeight,
                length=totalLength,
                geometry=combinedGeometry,
                original_osmids=originalOsmids,
                mode={"type": "walk"}
            )

        with perfTimer("Add shortest path from src to every route"):
            # From user source node to route
            dist_src, path_src = nx.single_source_dijkstra(walkingG, source=srcNode, weight='weight')

            # Loop through each route for srcNodeUser to find its shortest path
            for route in os.listdir(relativePath):

                routeNodes = {'northbound': {}, 'southbound': {}}

                with open(f'{relativePath}/{route}/{route}_nodes.geojson', 'r') as file:
                    f = json.load(file)


                for i in f['features']:
                    if i['properties']['mode']['details']['bound'] == 'north':
                        routeNodes['northbound'][i['properties']['osmid']] = {
                            'x': i['properties']['x'],
                            'y': i['properties']['y']
                        }
                    else:
                        routeNodes['southbound'][i['properties']['osmid']] = {
                            'x': i['properties']['x'],
                            'y': i['properties']['y']
                        }
                        

                # bound (northbound, southbound) / routeArr {900: {'x': 1.2, 'y': 3.4}}
                for bound, routeArr in routeNodes.items():
                    if routeArr:
                        
                        # list of equivalent nodes on the walking graph
                        routeOnWalkingG = [
                            coord_to_walking_node[(val['x'], val['y'])]
                            for val in routeArr.values()
                            if (val['x'], val['y']) in coord_to_walking_node
                        ]

                        # Gets the best equivalent route node with on the walking graph
                        best_node = min(routeOnWalkingG, key=lambda n: dist_src.get(n, float('inf')))

                        # Looks for its route node counterpart
                        for key, value in routeArr.items():
                            if value['x'] == walkingG.nodes[best_node]['x'] and value['y'] == walkingG.nodes[best_node]['y']:
                                bestRouteNode = key
                                break
                        srcToFirstRoute = list(path_src[best_node])
                        srcToFirstRoute.append(bestRouteNode)

                        collapseBySegment(G, minimizedG, srcToFirstRoute)

                        # minimizedG.add_edge(path_src[best_node][0], bestRouteNode, weight=dist_src[best_node])

                        # From route to user destination node
                        dist_dest, path_dest = nx.multi_source_dijkstra(walkingG, sources=set(routeOnWalkingG), target=destNode, weight='weight')
                        best_node = path_dest[0]

                        # Get the routeArr's node from the best walking node
                        for key, value in routeArr.items():
                            if value['x'] == walkingG.nodes[best_node]['x'] and value['y'] == walkingG.nodes[best_node]['y']:
                                bestRouteNode = key
                                break

                        # Initialize path from route's best node to destination node
                        srcRouteToDestNode = path_dest
                        srcRouteToDestNode.insert(0, bestRouteNode)

                        collapseBySegment(G, minimizedG, srcRouteToDestNode)
            
        with perfTimer("add trike connections"):
            with perfTimer("src to nearest"):
                # --- Connect src node to nearest tricycle terminal --- #
                closestTerminal = None
                shortestDistance = None
                for coord, feature in coord_to_node_terminal.items():

                    distance = haversine(walkingG.nodes[srcNode]['y'], walkingG.nodes[srcNode]['x'], coord[1], coord[0])

                    if shortestDistance is None or distance < shortestDistance:
                        shortestDistance = distance
                        closestTerminal = feature

                terminalNodeOnWalking = None
                for node, data in walkingG.nodes(data=True):
                    if data['x'] == closestTerminal['properties']['x'] and data['y'] == closestTerminal['properties']['y']:
                        terminalNodeOnWalking = node

                pathToTerminal = ox.shortest_path(walkingG, srcNode, terminalNodeOnWalking, weight="weight")
                pathToTerminal.append(closestTerminal['properties']['osmid'])

                collapseBySegment(G, minimizedG, pathToTerminal)

            with perfTimer("every terminal to dest"):
                # ----------------------------------------------------- #
                # Connect dest node from every terminal inside subgraph #
                # Checks if dest node is inside a trike subgraph
                if (G.nodes[destNode]['x'], G.nodes[destNode]['y']) in coord_to_node_subg:
                    subgraphName = coord_to_node_subg[(G.nodes[destNode]['x'], G.nodes[destNode]['y'])]['properties']['mode']['details']['name']

                    # Collect all terminals belonging to a subgraph where the dest node is in
                    terminalsInSubgraph = [n['properties']['osmid'] for n in coord_to_node_terminal.values() 
                                        if n['properties']['mode']['details']['name'] == subgraphName]

                    # Single shortest-path search from destNode outward (on reversed graph),
                    # reused for every terminal instead of running a separate search per terminal
                    lengths, pathsFromDest = nx.single_source_dijkstra(
                        G.reverse(copy=False),
                        source=destNode,
                        weight="weight"
                    )

                    for terminal in terminalsInSubgraph:
                        if terminal not in pathsFromDest:
                            continue

                        # Reverse back since the search ran from destNode outward
                        pathToDestNode = pathsFromDest[terminal][::-1]

                        collapseBySegment(G, minimizedG, pathToDestNode)
                # ----------------------------------------------------- #
            
        with perfTimer("do dijkstra"):
            if algo == 'dijkstra':
                theList = list(ox.k_shortest_paths(minimizedG, srcNode, destNode, 10, weight="weight"))
            elif algo == 'astar':
                theList = list(get_k_shortest_paths(minimizedG, srcNode, destNode, 10, weight="weight"))
            else:
                raise ValueError("Undefined algorithm")

        with perfTimer("find all permutations"):
            permutationList = []
            routeList = []
            for i in theList:
                # print(i)
                permutation = []
                route = i.copy()

                for j in range(len(i)):

                    # Determine this node's mode label
                    nodeMode = minimizedG.nodes[i[j]]['mode']
                    modeType = 'walk' if nodeMode['type'] == 'walk' else nodeMode['details']['name']
                    modeType = modeType.removesuffix("-Southbound").removesuffix("-Northbound")

                    # Check the edge leading into this node (if any) for a collapsed walk connector
                    edgeIsWalk = False
                    if j > 0:
                        edgeAttrs = minimizedG[i[j-1]][i[j]][0]
                        if edgeAttrs.get('mode', {}).get('type') == 'walk':
                            edgeIsWalk = True

                    if permutation:
                        # If the edge leading here was a collapsed walk segment, record 'walk'
                        # before recording this node's own mode, unless the last entry already is 'walk'
                        if edgeIsWalk and permutation[-1] != 'walk':
                            permutation.append('walk')

                        if modeType != permutation[-1]:
                            permutation.append('walk') if nodeMode['type'] == 'walk' else permutation.append(modeType)

                    else:  # First node in the calculated path
                        permutation.append('walk') if nodeMode['type'] == 'walk' else permutation.append(modeType)

                # Check if permutation is unique and does not have duplicate routes
                if permutation not in permutationList and not len({x for x in permutation if x != "walk"}) < len([x for x in permutation if x != "walk"]):
                    routeList.append(route)
                    permutationList.append(permutation)

        # for i in permutationList:
        #     print(i)

        resultsObj = {}
        resultsJson = {'routes': resultsObj}

        with perfTimer("filter permutations"):
            count = 1
            for i in routeList:
                # Maximum of 3 routes
                if count == 4:
                    break
                nodeList = []

                # Used to filter out paths that uses a route multiple times
                validRoute = True
                # Tracker for visited routes
                routesVisited = []

                prevNode = None

                print(i)
                # Loop through each node of the route
                for j in i:
                    node = G.nodes[j]

                    # Check if the edge leading into this node is a collapsed segment (any mode)
                    collapsedEdge = None
                    if prevNode is not None:
                        edgeAttrs = minimizedG[prevNode][j][0]
                        if 'original_osmids' in edgeAttrs and 'geometry' in edgeAttrs:
                            collapsedEdge = edgeAttrs

                    if node['mode']['type'] == 'walk':
                        colorPick = "#005eff"
                    elif node['mode']['details']['name'] in colors:
                        colorPick = colors[node['mode']['details']['name']]
                    else:
                        colorPick = "#000000"

                    if collapsedEdge:
                        geom = collapsedEdge['geometry']

                        if isinstance(geom, dict):
                            geom = shape(geom)

                        if geom.geom_type == 'LineString':
                            edgeCoords = [[float(x), float(y)] for x, y in geom.coords]
                        elif geom.geom_type == 'Point':
                            edgeCoords = [[float(geom.x), float(geom.y)]]
                        elif geom.geom_type == 'MultiLineString':
                            edgeCoords = []
                            for part in geom.geoms:
                                edgeCoords.extend([[float(x), float(y)] for x, y in part.coords])
                        else:
                            raise ValueError(f"Unexpected geometry type: {geom.geom_type}")

                        segMode = collapsedEdge['mode']['type']
                        if segMode == 'trike':
                            if nodeList[-1]['mode']['type'] == segMode:
                                segName = nodeList[-1]['mode']['details']['name']
                            else:
                                segName = node['mode']['details']['terminal']
                        else:
                            segName = collapsedEdge['mode']['details']['name'] if segMode != 'walk' else 'On foot'
                        segColor = "#005eff" if segMode == 'walk' else colors.get(collapsedEdge['mode']['details'].get('name'), "#000000")

                        # Check if current node is on the same mode path or not
                        if nodeList and nodeList[-1]['mode']['type'] == segMode and (segMode == 'walk' or nodeList[-1]['mode']['details']['name'] == segName):
                            # Extend existing same-mode segment with the full collapsed edge geometry
                            nodeList[-1]['geometry'].extend(edgeCoords)
                        else:
                            if segMode != 'walk' and segName in routesVisited:
                                validRoute = False
                                break

                            if nodeList:
                                nodeList[-1]['mode']['details']['fare'] = {
                                    'regular': getFare(modePathList=nodeList[-1]['geometry'], mode=nodeList[-1]['mode']['type'], discount=False),
                                    'discounted': getFare(modePathList=nodeList[-1]['geometry'], mode=nodeList[-1]['mode']['type'], discount=True)
                                }

                            nodeList.append({
                                'mode': {
                                    'type': segMode,
                                    'details': {
                                        'name': segName,
                                        'color': segColor
                                    }
                                },
                                'geometry': edgeCoords
                            })

                            if segMode != 'walk':
                                routesVisited.append(segName)

                        prevNode = j
                        continue

                    if nodeList:
                        if node['mode']['type'] == nodeList[-1]['mode']['type']:
                            nodeList[-1]['geometry'].append([float(node['x']), float(node['y'])])

                            # If this is a trike segment and we haven't resolved a terminal name yet,
                            # keep checking each subsequent node for a non-False terminal value
                            if node['mode']['type'] == 'trike' and nodeList[-1]['mode']['details']['name'] is None:
                                if node['mode']['details']['terminal'] is not False:
                                    nodeList[-1]['mode']['details']['name'] = node['mode']['details']['terminal']

                        else:
                            if node['mode']['type'] != 'walk' and node['mode']['details']['name'] in routesVisited:
                                validRoute = False
                                break
                            # Add fare for mode path
                            nodeList[-1]['mode']['details']['fare'] = {
                                'regular': getFare(modePathList=nodeList[-1]['geometry'], mode=nodeList[-1]['mode']['type'], discount=False),
                                'discounted': getFare(modePathList=nodeList[-1]['geometry'], mode=nodeList[-1]['mode']['type'], discount=True)
                            }

                            if node['mode']['type'] == 'trike':
                                resolvedName = node['mode']['details']['terminal'] if node['mode']['details']['terminal'] is not False else None
                            elif node['mode']['type'] == 'walk':
                                resolvedName = 'On foot'
                            else:
                                resolvedName = node['mode']['details']['name']

                            nodeList.append({
                                'mode': {
                                    'type': node['mode']['type'],
                                    'details': {
                                        'name': resolvedName,
                                        'color': colorPick
                                    }
                                },
                                'geometry': [
                                    [float(node['x']), float(node['y'])]
                                ]
                            })
                            if node['mode']['type'] != "walk":
                                routesVisited.append(node['mode']['details']['name'])
                    else:
                        if node['mode']['type'] == 'trike':
                            resolvedName = node['mode']['details']['terminal'] if node['mode']['details']['terminal'] is not False else None
                        elif node['mode']['type'] == 'walk':
                            resolvedName = 'On foot'
                        else:
                            resolvedName = node['mode']['details']['name']

                        nodeList.append({
                            'mode': {
                                'type': node['mode']['type'],
                                'details': {
                                    'name': resolvedName,
                                    'color': colorPick
                                }
                            },
                            'geometry': [
                                [float(node['x']), float(node['y'])]
                            ]
                        })
                        if node['mode']['type'] != "walk":
                            routesVisited.append(node['mode']['details']['name'])

                    prevNode = j

                    exhaustedRoutes = False
                    for modeRoute in nodeList:
                        if modeRoute['mode']['type'] != 'walk':
                            totalDist = 0
                            for u, v in zip(modeRoute['geometry'], modeRoute['geometry'][1:]):
                                totalDist += haversine(u[1], u[0], v[1], v[0])
                            if totalDist < 400:
                                exhaustedRoutes = True
                if exhaustedRoutes:
                    break

                if validRoute:
                    nodeList[len(nodeList)-1]['mode']['details']['fare'] = {
                        'regular': getFare(modePathList=nodeList[len(nodeList)-1]['geometry'], mode=nodeList[len(nodeList)-1]['mode']['type'], discount=False),
                        'discounted': getFare(modePathList=nodeList[len(nodeList)-1]['geometry'], mode=nodeList[len(nodeList)-1]['mode']['type'], discount=True)
                    }
                    resultsObj[f'result-{count}'] = nodeList
                    count+=1


            with perfTimer("get traffic data"):
                for resultX in resultsJson['routes']:
                    for modeRoute in resultsJson['routes'][resultX]:
                        totalDist = 0

                        # Calculate total distance of path
                        for u, v in zip(modeRoute['geometry'], modeRoute['geometry'][1:]):
                            totalDist += haversine(u[1], u[0], v[1], v[0])

                        # Get expected duration in seconds after converting km/h to m/s
                        if modeRoute['mode']['type'] == 'walk':
                            expectedDuration = totalDist / (WALK_SPEED / 3.6)
                        elif modeRoute['mode']['type'] == 'jeep':
                            expectedDuration = totalDist / (JEEP_SPEED / 3.6)
                        elif modeRoute['mode']['type'] == 'trike':
                            expectedDuration = totalDist / (TRIKE_SPEED / 3.6)
                        else:
                            expectedDuration = 0

                        try:
                            if traffic and modeRoute['mode']['type'] in ['jeep', 'trike'] and totalDist > 500:
                                API_KEY = API_KEY_HERE

                                
                                line = LineString(modeRoute['geometry'])
                                simplified = line.simplify(0.0001 , preserve_topology=False)
                                simplified_geometry = [list(coord) for coord in simplified.coords]

                                locations = "%3A".join(f"{point[1]}%2C{point[0]}" for point in simplified_geometry)

                                url = f"https://api.tomtom.com/routing/1/calculateRoute/{locations}/json"
                                parameters = {"routeRepresentation": "summaryOnly", "computeTravelTimeFor": "all", "sectionType": "traffic", "traffic": "true", "key": API_KEY}

                                response = requests.get(url, params=parameters)
                                trafficData = response.json()
                                

                                travelTimeSeconds = trafficData['routes'][0]['summary']['liveTrafficIncidentsTravelTimeInSeconds']

                                # Apply 
                                if trafficData['routes'][0]['summary']['trafficDelayInSeconds'] > 0:
                                    ratio = travelTimeSeconds / trafficData['routes'][0]['summary']['noTrafficTravelTimeInSeconds']
                                    ratio = max(ratio, 1.0)
                                else:
                                    ratio = 1.0

                                actualDuration = math.ceil(expectedDuration * ratio)
                            else:
                                actualDuration = math.ceil(expectedDuration)
                        except Exception:
                            traceback.print_exc()
                            actualDuration = 0

                        modeRoute['traffic'] = {
                            "expectedDuration": math.ceil(expectedDuration),
                            "actualDuration": actualDuration
                        }
                    

                                




        return resultsJson
                
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))