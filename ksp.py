import networkx as nx
import osmnx as ox
import geopandas as gpd
import numpy as np
import requests as req
import os
import json
from shapely.ops import linemerge
import copy
import math
from shapely.geometry import shape, LineString
from func import getNearestNodeId, getFare, haversine, getLengthMeters
from algo import get_k_shortest_paths


# --------------- INITIALIZE GRAPH --------------- #
# Read nodes and edges of Mabalacat and Angeles City
nodes = gpd.read_file("graph/transit_graph/walking_graph/mabalacatAngelesWalking_nodes.geojson")
edges = gpd.read_file("graph/transit_graph/walking_graph/mabalacatAngelesWalking_edges.geojson")

# Fix index of nodes and edges
nodes = nodes.set_index("osmid")
edges = edges.set_index(["u", "v", "key"])

# convert np arrays to lists"
for attr in edges.columns:
    new_values = []

    for val in edges[attr]:
        if isinstance(val, np.ndarray):
            new_values.append(val.tolist())
        else:
            new_values.append(val)

    edges[attr] = new_values

# Initialize MultiDiGraph
G = ox.graph_from_gdfs(nodes, edges)

# Copy MultiDiGraph to walking graph
walkingG = copy.deepcopy(G)
# -------------------------------------------------- #
# --------- INITIALIZE SIMPLIFIED GRAPH ------------ #

# Read nodes and edges of minimized transit graph"
nodes = gpd.read_file("graph/transit_graph/simplified_graph/simplifiedGraph_nodes.geojson")
edges = gpd.read_file("graph/transit_graph/simplified_graph/simplifiedGraph_edges.geojson")

# Fix index of nodes and edges
nodes = nodes.set_index("osmid")
edges = edges.set_index(["u", "v", "key"])

# Convert np arrays to lists
for attr in edges.columns:
    new_values = []

    for val in edges[attr]:
        if isinstance(val, np.ndarray):
            new_values.append(val.tolist())
        else:
            new_values.append(val)

    edges[attr] = new_values

minimizedG = ox.graph_from_gdfs(nodes, edges)
# -------------------------------------------------- #
# ------------------ ADD SUBGRAPHS ----------------- #
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
# ------------------ ADD JEEP ROUTES ----------------- #
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

def _max_osmid(base_path, suffix):
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
    _max_osmid("graph/transit_graph/trike_routes", "edges.geojson"),
    _max_osmid("graph/transit_graph/jeep_routes", "edges.geojson")
)

nodeIdIndex = max(
    _max_osmid("graph/transit_graph/trike_routes", "nodes.geojson"),
    _max_osmid("graph/transit_graph/jeep_routes", "nodes.geojson")
)

def _getNodeId():
    global edgeIdIndex
    current = edgeIdIndex
    edgeIdIndex +=1
    return current

def _getEdgeId():
    global nodeIdIndex
    current = nodeIdIndex
    nodeIdIndex +=1
    return current
# -------------------------------------------------- #
# -------------- ADD EDGE SEGMENT ------------------ #
def _collapseBySegment(G, targetG, path):
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

        combinedGeometry = LineString(allCoords)

        u, v = segmentNodes[0], segmentNodes[-1]



        # Only add the two boundary nodes actually used by this edge
        for osmid in (u, v):
            attrs = G.nodes[osmid].copy()
            targetG.add_node(osmid, **attrs)

            
        targetG.add_edge(
            u, v,
            osmid=str(_getEdgeId()),
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


def getJeepRoutes():
    '''
    Iterates through each jeep route folder and returns a list of objects
    pertaining to route information 
        {
            "id": "jeep-route-1",
            "name": "jeep-route-1",
            "color": "#ffffff",
            "geojson": jeep-route-1_edges.geojson
        }
    Parameters
    ----------
    None

    Returns
    ----------
    list[dict]
    '''
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
    return route_list

def getTrikeTerminalsList():
    '''
    Iterates through each tricycle subgraph folder and returns a list of objects
    pertaining to tricycle terminal information
        {
            "terminalName": "NAMETODA",
            "locationName": "Barangay, City",
            "coordinates": {
                "lat": latitude,
                "long": longitude
            }
        }
    --------
    Parameters
    ----------
    None

    Returns
    ----------
    list[dict]
    '''
    trikeGraphsDir = r"graph/transit_graph/trike_routes"

    # Map of TODA terminals to locations
    with open("graph_config/toda_locations.json", "r") as file:
        todaLocations = json.load(file)

    terminalList = []

    for subgraph in os.listdir(trikeGraphsDir):
        with open(f"{trikeGraphsDir}/{subgraph}/{subgraph}_nodes.geojson", "r") as file:
            nodesGeojson = json.load(file)
        for node in nodesGeojson['features']:
            terminalName = node['properties']['mode']['details']['terminal']
            if terminalName != False:
                terminalList.append({
                    "terminalName": terminalName,
                    "locationName": todaLocations.get(terminalName, ""),
                    "coordinates": {
                        "lat": node['properties']['y'],
                        "long": node['properties']['x'],
                    },
                })
    return terminalList


# --------- K SHORTEST PATHS ----------- #
def _walkSrcToDest(srcNode: int, destNode: int):
    '''
    Adds a connection between user's source and destination node on
    the minimized graph.
    Uses the walking graph to find the shortest path from src to dest.

    Parameters
    ----------
    srcNode
        OSM_ID of user's source node on the graph

    destNode
        OSM_ID of user's destination node on the graph

    Returns
    ----------
    None
        
    '''
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
        osmid=str(_getEdgeId()),
        weight=totalWeight,
        length=totalLength,
        geometry=combinedGeometry,
        original_osmids=originalOsmids,
        mode={"type": "walk"}
    )

def _connectRoutesToSrcDest(srcNode: int, destNode: int):
    '''
    Adds a shortest path from source node to every jeepney route on minimized graph,
    and adds a shortest path from every jeepney route to destination node.
    
    It iterates from the user's starting node and finds the shortest path to each
    jeepney route (northbound & southbound if applicable), then creates a collapsed
    segment between node and the route to add to the minimized graph. Does the same
    with destination node.

    Parameters
    ----------
    srcNode
        OSM_ID of user's source node on the graph

    destNode
            OSM_ID of user's destination node on the graph

    Returns
    ----------
    None
    
    '''

    # dictionary lookup of coordinate tuples mapped to walking node IDs
    coord_to_walking_node = {
        (data['x'], data['y']): node
        for node, data in walkingG.nodes(data=True)
    }

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

                _collapseBySegment(G, minimizedG, srcToFirstRoute)

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

                _collapseBySegment(G, minimizedG, srcRouteToDestNode)

def _trikeConnections(srcNode: int, destNode: int):
    '''
    Adds connections between source/dest nodes and select tricycle terminals.
    Connects source node to nearest trike terminal on its adjacent trike subgraph, 
    while dest node is connected from every trike terminal on its adjacent subgraph

    Parameters
    ----------
    srcNode
        OSM_ID of user's source node on the graph

    destNode
        OSM_ID of user's destination node on the graph

    Returns
    ----------
    None
    
    '''
    # -------- SRC NODE TO NEAREST TRIKE TERMINAL --------- #
    # ----------------------------------------------------- #
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

    _collapseBySegment(G, minimizedG, pathToTerminal)
    # ----------------------------------------------------- #

    # ------------- EVERY TERMINAL TO DEST NODE ----------- #
    # ----------------------------------------------------- #
    # Connect dest node from every terminal inside subgraph #
    # Checks if dest node is inside a trike subgraph        #
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

            _collapseBySegment(G, minimizedG, pathToDestNode)
    # ----------------------------------------------------- #

def _kShortestPathAlgo(algo: str, graph: nx.MultiDiGraph, src: int, dest: int, k: int, weight: str="weight"):
    '''
    Calculates list of shortest paths using Yen's + shortest path algorithm on a specified graph.

    Parameters
    ----------
    algo
        A string literal containing shortest path algorithm to use, using 'astar' as default

    graph
        A MultiDiGraph where the KSP algorithm will calculate on

    src
        OSM_ID of user's source node on the graph

    src
        OSM_ID of user's destination node on the graph

    k
        Number of iterations Yen's algorithm should calculate shortest paths

    weight
        weight to use for the graph, default as "weight"

    Returns
    ----------
    list[list[int]]
    
    '''
    if algo == 'dijkstra':
        theList = list(ox.k_shortest_paths(graph, src, dest, k, weight=weight))    # Uses OSMNx's k_shortest_path function using bidirectional dijkstra's
    elif algo == 'astar':
        theList = list(get_k_shortest_paths(graph, src, dest, k, weight=weight))   # Uses own A* algorithm
    else:
        raise ValueError("Undefined algorithm")
    return theList

def _filterRoutes(rawList: list[list[int]]):
    '''
    Returns a dictionary of route results formatted as JSON without traffic
    details.

    Accepts raw unfiltered list of k shortest paths and filters every duplicate
    permutation of multimodal routes (e.g walk-jeep1-walk is a unique permutation),
    then formats it into a JSON object with attribute names added. Fare is also added
    in this function.

    Parameters
    ----------
    rawList
        unfiltered list of k shortest path lists calculated from get_k_shortest_paths()

    Returns
    ----------
    dict[str, dict]

    '''
    permutationList = []
    routeList = []
    resultsObj = {}
    for i in rawList:
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

        exhaustedRoutes = False
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
                            if nodeList[-1]['mode']['type'] != 'walk' and getLengthMeters(nodeList[-1]['geometry']) < 400:
                                exhaustedRoutes = True
                                break
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

                # Usually the first node or a jeep node
                if nodeList:
                    if node['mode']['type'] == nodeList[-1]['mode']['type']:
                        nodeList[-1]['geometry'].append([float(node['x']), float(node['y'])])

                        # If this is a trike segment and we haven't resolved a terminal name yet,
                        # keep checking each subsequent node for a non-False terminal value
                        if node['mode']['type'] == 'trike' and nodeList[-1]['mode']['details']['name'] is None:
                            if node['mode']['details']['terminal'] is not False:
                                nodeList[-1]['mode']['details']['name'] = node['mode']['details']['terminal']

                    else:

                        # Check if jeep route has not been previously visited in the path
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
            if exhaustedRoutes:
                break

            if validRoute:
                nodeList[len(nodeList)-1]['mode']['details']['fare'] = {
                    'regular': getFare(modePathList=nodeList[len(nodeList)-1]['geometry'], mode=nodeList[len(nodeList)-1]['mode']['type'], discount=False),
                    'discounted': getFare(modePathList=nodeList[len(nodeList)-1]['geometry'], mode=nodeList[len(nodeList)-1]['mode']['type'], discount=True)
                }
                resultsObj[f'result-{count}'] = nodeList
                count+=1
    return resultsObj

def _queryTraffic(geom: list[list[int]]):
    '''
    Queries traffic data from TomTom Routing API based on an edge geometry

    Parameters
    ----------
    geom
        Edge geometry consisting of coordinates as list inside a list

    Returns
    ----------
    dict[str, dict]
    '''
    API_KEY = API_KEY_HERE

    locations = "%3A".join(f"{point[1]}%2C{point[0]}" for point in geom)
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{locations}/json"
    parameters = {"routeRepresentation": "summaryOnly", "computeTravelTimeFor": "all", "sectionType": "traffic", "traffic": "true", "key": API_KEY}

    response = req.get(url, params=parameters)
    return response

        
def _getTrafficData(resultsJson: dict[str, dict], traffic: bool):
    '''
    Adds traffic data to JSON response dictionary. 
    
    If traffic is toggled on, it queries from TomTom Routing API to 
    get traffic details of each vehicle mode path geometry from 
    every route result. Otherwise, use average mode speed for
    actual duration.

    Parameters
    ----------
    resultsJson
        JSON response dictionary without "traffic" key

    traffic
        boolean value indicating if historical traffic data is to be used

    Returns
    ----------
    dict[str, dict]
    '''

    # Dict of vehicle routes geometry to reuse traffic duration
    listOfRoutesGeom = {}                   
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
                    

                    
                    line = LineString(modeRoute['geometry'])
                    simplified = line.simplify(0.0001 , preserve_topology=False)
                    simplified_geometry = [list(coord) for coord in simplified.coords]
                    geomKey = tuple(tuple(coord) for coord in simplified_geometry)

                    if geomKey in listOfRoutesGeom:
                        actualDuration = listOfRoutesGeom[geomKey]
                    else:
                        response = _queryTraffic(simplified_geometry)
                        trafficData = response.json()
                        
                        travelTimeSeconds = trafficData['routes'][0]['summary']['historicTrafficTravelTimeInSeconds']

                        # Gets the ratio of traffic slowdown to expected duration based from API without traffic
                        if trafficData['routes'][0]['summary']['trafficDelayInSeconds'] > 0:
                            ratio = travelTimeSeconds / trafficData['routes'][0]['summary']['noTrafficTravelTimeInSeconds']
                            ratio = max(ratio, 1.0)
                        else:
                            ratio = 1.0

                        # Apply ratio to expected duration based on average mode speeds
                        actualDuration = math.ceil(expectedDuration * ratio)
                        listOfRoutesGeom[geomKey] = actualDuration
                else:
                    actualDuration = math.ceil(expectedDuration)
            except Exception:
                actualDuration = 0
            modeRoute['traffic'] = {
                "expectedDuration": math.ceil(expectedDuration),
                "actualDuration": actualDuration
            }
    return resultsJson

def getKShortestPathsJson(src: str, dest: str, algo: str, traffic: bool):
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

    algo
        A string literal containing shortest path algorithm to use, using 'astar' as default

    traffic
        A boolean value to determine if a third-party API will be used to source traffic details of results, using False as default

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

        # Get nearest node from user inputs
        srcNode = getNearestNodeId(walkingG, pair['source']['lat'], pair['source']['long'])
        destNode = getNearestNodeId(walkingG, pair['destination']['lat'], pair['destination']['long'])

        # Get src node data from graph and add to minimized graph
        node_data = walkingG.nodes[srcNode]
        minimizedG.add_node(srcNode, **node_data)

        # Get dest node data from graph and add to minimized graph
        node_data = walkingG.nodes[destNode]
        minimizedG.add_node(destNode, **node_data)

        _walkSrcToDest(srcNode=srcNode, destNode=destNode)                                                              # Add edge from user src node to user dest node in minimized graph

        _connectRoutesToSrcDest(srcNode=srcNode, destNode=destNode)                                                     # Add edge from user src/dest to every jeep route in minimized graph

        _trikeConnections(srcNode=srcNode, destNode=destNode)                                                           # Add tricycle terminal connections
        
            
        rawKSPList = _kShortestPathAlgo(algo=algo, graph=minimizedG, src=srcNode, dest=destNode, k=10, weight="weight") # Get list of k shortest paths

        resultsObj = _filterRoutes(rawKSPList)                                                                          # Get formatted JSON response dictionary

        resultsJson = {'routes': resultsObj}                                                                            
        resultsJson = _getTrafficData(resultsJson=resultsJson, traffic=traffic)                                         # Add traffic data to JSON response

        return resultsJson

    except ValueError as e:
        raise ValueError(e)
    except Exception as e:
        raise Exception("Internal Server Error")