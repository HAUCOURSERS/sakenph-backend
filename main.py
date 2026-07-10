from fastapi import FastAPI, HTTPException
import networkx as nx
import time
from contextlib import contextmanager
import osmnx as ox
import geopandas as gpd
import numpy as np
import os
import json
import copy
from shapely.geometry import shape
from func import getNearestNodeId
from algo import get_k_shortest_paths
import itertools

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
# ------------------ ADD ROUTES -------------------- #
with perfTimer("add routes"):
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
# ------------------ ADD COLOR HASH ---------------- #
with open(f"graph_config/color.json") as f:
    colors = json.load(f)
# -------------------------------------------------- #

app = FastAPI()

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

@app.get("/shortest_path")
def shortestPathTest(src: str, dest: str):
    '''
    Returns a dictionary of a multimodal route calculated by shortest path algorithm which contains the separate
    routes to traverse including the path of the mode in order.

    --- EXAMPLE RESULT ---
    {
        route: [
            { 
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
                ]
            },
            { 
            'mode': {
                'type': 'jeep',
                'details: {
                    'name': 'route-1',
                    'color': '#1d7021'
                }
            },
            'jeep'
            'geometry': [
                    [120.58833604642595, 15.1434826439334],
                    [120.58791499937249, 15.14178736453769],
                    [120.58745810400315, 15.139206114741604]
                ]
            },
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
                ]
            }
        ]
    }
    In the example above, a calculated route would be a person from its origin node walk to the nearest path
    with a jeepney route, then hops on the line until it drops off to the nearest stop from its final destination,
    where the person would walk until the destination node.
    -------------------
    
    Parameters
    ----------
    src
        A string literal containing latitude and longitude values for source coordinates separated by comma

    dest
        A string literal containing latitude and longitude values for destination coordinates separated by comma
    Returns
    ----------
    None
    '''
    try:
        pair = {
            'source': {'lat': float(src.split(',')[0]), 'long': float(src.split(',')[1])},
            'destination': {'lat': float(dest.split(',')[0]), 'long': float(dest.split(',')[1])},
        }

        # Gets the nearest node from each source/destination coordinates
        with perfTimer("get nearest node id"):
            srcNode = getNearestNodeId(G, pair['source']['lat'], pair['source']['long'])
            destNode = getNearestNodeId(G, pair['destination']['lat'], pair['destination']['long'])

        # The shortest path algorithm (weight attribute is pre-calculated as the time it takes to  
        # traverse an edge in seconds based on its mode's average speed
        with perfTimer('do shortest path'):
            pathList = ox.k_shortest_paths(G, srcNode, destNode, 1, weight="weight")

        with perfTimer('append'):
            final = list(itertools.chain.from_iterable(pathList))
        nodeList = []
        for i in final:
            node = G.nodes[i]
            if nodeList:
                # print(f'{node['mode']['type']}: {i}')
                if node['mode']['type'] == nodeList[len(nodeList)-1]['mode']['type']:
                    nodeList[len(nodeList)-1]['geometry'].append([float(node['x']), float(node['y'])])
                else:
                    nodeList.append({
                        'mode': {
                            'type': node['mode']['type'],
                            'details': {
                                'name': node['mode']['details']['name'] if node['mode']['type'] != 'walk' else 'On foot',
                                'color': colors[node['mode']['details']['name']] if node['mode']['type'] != 'walk' else "#005eff"
                            }
                        },
                        'geometry': [
                            [float(node['x']), float(node['y'])]
                        ] 
                    })
            else:
                nodeList.append({
                    'mode': {
                        'type': node['mode']['type'],
                        'details': {
                            'name': node['mode']['details']['name'] if node['mode']['type'] != 'walk' else 'On foot',
                            'color': colors[node['mode']['details']['name']] if node['mode']['type'] != 'walk' else "#005eff"
                        }
                    },
                    'geometry': [
                        [float(node['x']), float(node['y'])]
                    ]
                })

        return {'route': nodeList}

        # with perfTimer("do Dijkstra's"):
        #     finalDistance, pathList = nx.multi_source_dijkstra(G, [start], end, weight="length")
    except Exception as e:
        raise Exception(status_code=500, detail=str(e))
    
@app.get("/k_shortest_paths")
def kShortestPaths(src: str, dest: str, algo:str='astar', debug:str='false'):
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
                    ]
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
                    ]
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
                    ]
                }
            },
            result-2: {
                0: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': []},
                1: {'mode': {'type': 'walk', 'details': {'name': 'route-2', 'color': '#a11ea6'}}, 'geometry': []},
                2: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': []},
                3: {'mode': {'type': 'walk', 'details': {'name': 'route-3', 'color': '#f0cf13'}}, 'geometry': []},
                4: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': []}
            },
            result-3: {
                0: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': []},
                1: {'mode': {'type': 'walk', 'details': {'name': 'route-4', 'color': '#7c4dc4'}}, 'geometry': []},
                2: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': []},
                3: {'mode': {'type': 'walk', 'details': {'name': 'toda-1', 'color': '#ba1c59'}}, 'geometry': []},
                4: {'mode': {'type': 'walk', 'details': {'name': 'On foot', 'color': '#2005ed'}}, 'geometry': []}
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

        
        print(f'src lat-y,long-x: {pair['source']['lat']},{pair['source']['long']}')
        print(f'dest lat-y,long-x: { pair['destination']['lat']},{pair['destination']['long']}')

        srcNode = getNearestNodeId(G, pair['source']['lat'], pair['source']['long'])
        destNode = getNearestNodeId(G, pair['destination']['lat'], pair['destination']['long'])

        node_data = G.nodes[srcNode]
        minimizedG.add_node(srcNode, **node_data)

        node_data = G.nodes[destNode]
        minimizedG.add_node(destNode, **node_data)

        # Dictionary of x,y and nodeid pairs
        coord_to_walking_node = {
            (data['x'], data['y']): node
            for node, data in walkingG.nodes(data=True)
        }

        # ADD WALKING PATH FROM SOURCE NODE TO DEST NODE
        src_to_dest_dist, src_to_dest_path = nx.single_source_dijkstra(walkingG, source=srcNode, target=destNode, weight='weight')

        
        for osmid in src_to_dest_path:

            # Remove osmid first to readd it (clunky fix)
            attrs = G.nodes[osmid].copy()
            attrs.pop("osmid", None)
            minimizedG.add_node(osmid, **attrs)

        # Add connection from source node to dest node
        for u, v in zip(src_to_dest_path, src_to_dest_path[1:]):
            attrs = G[u][v][0]
            minimizedG.add_edge(u, v, **attrs)


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
                    srcToFirstRoute = path_src[best_node]

                    for osmid in srcToFirstRoute:

                        # Remove osmid first to readd it (clunky fix)
                        attrs = G.nodes[osmid].copy()
                        attrs.pop("osmid", None)
                        minimizedG.add_node(osmid, **attrs)

                    # Add connection from source node to first route node
                    for u, v in zip(srcToFirstRoute, srcToFirstRoute[1:]):
                        attrs = G[u][v][0]
                        minimizedG.add_edge(u, v, **attrs)


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

                    # Add walking nodes path to minimized graph
                    for osmid in srcRouteToDestNode:

                        # Remove osmid first to readd it (clunky fix)
                        attrs = G.nodes[osmid].copy()
                        attrs.pop("osmid", None)
                        minimizedG.add_node(osmid, **attrs)


                    srcRouteToDestNode.insert(0, bestRouteNode)

                    for osmid in srcRouteToDestNode:

                        # Remove osmid first to readd it (clunky fix)
                        attrs = G.nodes[osmid].copy()
                        attrs.pop("osmid", None)
                        minimizedG.add_node(osmid, **attrs)

                    # Add connection from route's best node to destination node
                    for u, v in zip(srcRouteToDestNode, srcRouteToDestNode[1:]):
                        attrs = G[u][v][0]
                        minimizedG.add_edge(u, v, **attrs)
                    
                    # minimizedG.add_edge(bestRouteNode, destNode, weight=dist_dest)

        if algo == 'dijkstra':
            theList = list(ox.k_shortest_paths(minimizedG, srcNode, destNode, 10, weight="weight"))
        elif algo == 'astar':
            theList = list(get_k_shortest_paths(minimizedG, srcNode, destNode, 10, weight="weight"))
        else:
            raise ValueError("Undefined algorithm")
        

        permutationList = []
        routeList = []
        for i in theList:
            permutation = []
            route = i.copy()

            for j in range(len(i)):
                
                if permutation:
                    modeType = minimizedG.nodes[i[j]]['mode']['type'] if minimizedG.nodes[i[j]]['mode']['type'] == 'walk' else minimizedG.nodes[i[j]]['mode']['details']['name']

                    # Removes bound suffix
                    modeType = modeType.removesuffix("-Southbound").removesuffix("-Northbound")

                    if modeType != permutation[-1]:  # Check if the previous mode is the same as the current node's mode
                        permutation.append('walk') if minimizedG.nodes[i[j]]['mode']['type'] == 'walk' else permutation.append(
                            modeType
                        )

                else:  # First node in the calculated path
                    permutation.append('walk') if minimizedG.nodes[i[j]]['mode']['type'] == 'walk' else permutation.append(
                        modeType
                    )


            # total_weight = sum(minimizedG[u][v][0].get('weight', 0) for u, v in zip(i[:-1], i[1:]))
            # # print(f"Weight: {total_weight:.2f}: {permutation}")

            if permutation not in permutationList:
                # print(f"1: {i}")
                # print(f"2: {route}")
                routeList.append(route)
                permutationList.append(permutation)

        for i in permutationList:
            print(i)

        resultsObj = {}
        resultsJson = {'routes': resultsObj}

        count = 1
        for i in routeList:
            # Maximum of 3 routes
            if count == 4:
                break # FIX THIS LATER
            nodeList = []
            # Loop through each node of the route
            for j in i:
                node = G.nodes[j]
                if nodeList:
                    # print(f'{node['mode']['type']}: {i}')
                    if node['mode']['type'] == nodeList[len(nodeList)-1]['mode']['type']:
                        nodeList[len(nodeList)-1]['geometry'].append([float(node['x']), float(node['y'])])
                    else:
                        nodeList.append({
                            'mode': {
                                'type': node['mode']['type'],
                                'details': {
                                    'name': node['mode']['details']['name'] if node['mode']['type'] != 'walk' else 'On foot',
                                    'color': colors[node['mode']['details']['name']] if node['mode']['type'] != 'walk' else "#005eff"
                                }
                            },
                            'geometry': [
                                [float(node['x']), float(node['y'])]
                            ] 
                        })
                else:
                    nodeList.append({
                        'mode': {
                            'type': node['mode']['type'],
                            'details': {
                                'name': node['mode']['details']['name'] if node['mode']['type'] != 'walk' else 'On foot',
                                'color': colors[node['mode']['details']['name']] if node['mode']['type'] != 'walk' else "#005eff"
                            }
                        },
                        'geometry': [
                            [float(node['x']), float(node['y'])]
                        ]
                    })
            resultsObj[f'result-{count}'] = nodeList
            count+=1
        return resultsJson
                
    except Exception as e:
        raise Exception(status_code=500, detail=str(e))
    
@app.get("/k_shortest_paths_debug")
def kShortestPathsDebug(src: str, dest: str, algo: str = "dijkstra"):
    elapsedList = []
    @contextmanager
    def perfReturn(action=""):
        start = time.perf_counter()
        yield
        end = time.perf_counter()
        elapsedList.append({f"Elapsed time to {action}": f" {round(end - start, 2)}s"})

    try:

        # Splits source and destination arguments from API link into separate dicts of coordinates
        pair = {
            'source': {'lat': float(src.split(',')[0]), 'long': float(src.split(',')[1])},
            'destination': {'lat': float(dest.split(',')[0]), 'long': float(dest.split(',')[1])},
        }
        with perfReturn("get nearest node id"):
            srcNode = getNearestNodeId(G, pair['source']['lat'], pair['source']['long'])
            destNode = getNearestNodeId(G, pair['destination']['lat'], pair['destination']['long'])

        # Add source and destination nodes to the minimized graph
        node_data = G.nodes[srcNode]
        minimizedG.add_node(srcNode, **node_data)

        node_data = G.nodes[destNode]
        minimizedG.add_node(destNode, **node_data)


        coord_to_walking_node = {
            (data['x'], data['y']): node
            for node, data in walkingG.nodes(data=True)
        }

        # From user source node to route
        dist_src, path_src = nx.single_source_dijkstra(walkingG, source=srcNode, weight='weight')

        # Loop through each route for srcNodeUser to find its shortest path
        with perfReturn("connect source and dest nodes to each route"):
            for route in os.listdir(relativePath):

                routeNodes = {'northbound': {}, 'southbound': {}}

                with open(f'{relativePath}/{route}/{route}_nodes.geojson', 'r') as file:
                    f = json.load(file)

                # Get every node from the route
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
                        

                # route (northbound, southbound) / routeArr {900: {'x': 1.2, 'y': 3.4}}
                for route, routeArr in routeNodes.items():
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


                        minimizedG.add_edge(path_src[best_node][0], bestRouteNode, weight=dist_src[best_node])

                        # From route to user destination node
                        dist_dest, path_dest = nx.multi_source_dijkstra(walkingG, sources=set(routeOnWalkingG), target=destNode, weight='weight')
                        best_node = path_dest[0]
    
                        # Get the routeArr's node from the best walking node
                        for key, value in routeArr.items():
                            if value['x'] == walkingG.nodes[best_node]['x'] and value['y'] == walkingG.nodes[best_node]['y']:
                                bestRouteNode = key
                                break
                        
                        minimizedG.add_edge(bestRouteNode, destNode, weight=dist_dest)

        with perfReturn("get shortest paths"):
            if algo == 'dijkstra':
                theList = list(ox.k_shortest_paths(minimizedG, srcNode, destNode, 5, weight="weight"))
            elif algo == 'astar':
                theList = list(get_k_shortest_paths(minimizedG, srcNode, destNode, 5, weight="weight"))
            else:
                raise ValueError("Undefined algorithm")

        permutationList = []
        routeList = []

        with perfReturn("Get modes of the list"):
            for i in range(len(theList[0])):
                node = theList[0][i]
                data = minimizedG.nodes[node]
                if i > 0:
                    prev = theList[0][i-1]
                    edge = minimizedG[prev][node]

        # with perfReturn("Extend modes"):
        #     for i in theList:
        #         permutation = []
        #         route = i.copy()

        #         # Used to offset the index of where to insert extension of two routes with walking path
        #         offset = 0
        #         for j in range(len(i)):
                    
        #             if permutation:
        #                 modeType = minimizedG.nodes[i[j]]['mode']['type'] if minimizedG.nodes[i[j]]['mode']['type'] == 'walk' else minimizedG.nodes[i[j]]['mode']['details']['name']

        #                 # Removes bound suffix
        #                 modeType = modeType.removesuffix("-Southbound").removesuffix("-Northbound")


        #                 if modeType != permutation[-1]:  # Check if the previous mode is the same as the current node's mode
        #                     extended = ox.shortest_path(G, i[j-1], i[j], weight="weight")

        #                     # Checks if there are additional nodes after extending the different modes
        #                     if len(extended) > 2:
        #                         route[j+offset:j+offset] = extended[1:-1]
        #                         offset += len(extended[1:-1])

        #                     permutation.append('walk') if minimizedG.nodes[i[j]]['mode']['type'] == 'walk' else permutation.append(
        #                         modeType
        #                     )

        #             else:  # First node in the calculated path
        #                 permutation.append('walk') if minimizedG.nodes[i[j]]['mode']['type'] == 'walk' else permutation.append(
        #                     modeType
        #                 )


        #         total_weight = sum(minimizedG[u][v][0].get('weight', 0) for u, v in zip(i[:-1], i[1:]))
        #         # print(f"Weight: {total_weight:.2f}: {permutation}")

        #         if permutation not in permutationList:
        #             # print(f"1: {i}")
        #             # print(f"2: {route}")
        #             routeList.append(route)
        #             permutationList.append(permutation)

        for i in permutationList:
            print(i)

        resultsObj = {}
        resultsJson = {'performancee': elapsedList, 'routes': resultsObj}

        with perfReturn("convert nodes of each result into json format:"):
            count = 1
            for i in routeList:

                # Maximum of 3 routes
                if count == 3:
                    break # FIX THIS LATER
                nodeList = []
                # Loop through each node of the route
                for j in i:
                    node = G.nodes[j]

                    if nodeList:
                        # print(f'{node['mode']['type']}: {i}')
                        if node['mode']['type'] == nodeList[len(nodeList)-1]['mode']:
                            nodeList[len(nodeList)-1]['nodes'].append({'osmid': j, 'y,x': f'{float(node['x'])},{float(node['y'])}'})
                        else:
                            nodeList.append({
                                'mode': node['mode']['details']['name'] if node['mode']['type'] != 'walk' else 'On foot',
                                'nodes': [
                                    {'osmid': j, 'y,x': f'{float(node['x'])},{float(node['y'])}'}
                                ] 
                            })
                    else:
                        nodeList.append({
                            'mode': node['mode']['details']['name'] if node['mode']['type'] != 'walk' else 'On foot',
                            'nodes': [
                                {'osmid': j, 'y,x': f'{float(node['x'])},{float(node['y'])}'}
                            ]
                        })
                resultsObj[f'result-{count}'] = nodeList
                count+=1
            return resultsJson
                   
    except Exception as e:
        raise Exception(status_code=500, detail=str(e))

# Testing single directional Dijkstra's
@app.get("/shortest_path_test")
def shortestPathTestf():

    @contextmanager
    def perfTimer(action=""):
        start = time.perf_counter()
        yield
        end = time.perf_counter()
        print(f"Elapsed time to {action}: {round(end - start, 2)}s")

    with perfTimer("read nodes and edges of mabalacat+angeles City"):
        nodes = gpd.read_file("graph/mabalacatAngeles_nodes.geojson")
        edges = gpd.read_file("graph/mabalacatAngeles_edges.geojson")

    with perfTimer("Fix index of nodes and edges then create MultiDiGraph G"):
        nodes = nodes.set_index("osmid")
        edges = edges.set_index(["u", "v", "key"])
        G = ox.graph_from_gdfs(nodes, edges)

    # Start node
    start = 3289714296
    # End node
    end = 2627301958

    with perfTimer("do Dijkstra's"):
        finalDistance, pathList = nx.multi_source_dijkstra(G, [start], end, weight="length")