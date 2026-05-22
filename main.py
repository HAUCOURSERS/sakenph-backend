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
def kShortestPathsTest(src: str, dest: str):
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

        # Gets the nearest node from each source/destination coordinates
        with perfTimer("get nearest node id"):
            srcNode = getNearestNodeId(G, pair['source']['lat'], pair['source']['long'])
            destNode = getNearestNodeId(G, pair['destination']['lat'], pair['destination']['long'])

        # Contains list of results
        routesResultsList = []

        # In
        initialModes = []
        modeList = []
        with perfTimer("make a copy of G"):
            nextG = copy.deepcopy(G)
        lastLength = None
        while (len(routesResultsList) < 3):
            with perfTimer("calculate an iteration:"):
                theList = list(itertools.chain.from_iterable(ox.k_shortest_paths(nextG, srcNode, destNode, 1, weight="weight")))
                
                # Check if current k shortest path is more than 25% of the previous k shortest path, which means you've exhausted all possible paths for that nextG
                length = nx.path_weight(G, theList, weight="weight")
                print(length)
                if lastLength and lastLength * 1.25 < length:
                    print("True")
                    if modeList:
                        if modeList[0] in initialModes:
                            nextG = copy.deepcopy(G)
                    else:
                        break
                else:
                    print("Not true")
                lastLength = length

                routesResultsList.append(theList)

                routeToRemove = None
                # Get all modes of route
                for i in theList:
                    if G.nodes[i]['mode']['type'] != 'walk':
                        modeList.append(G.nodes[i]['mode']['details']['name'])
                        
                if not initialModes:
                    initialModes = modeList

                if modeList:
                    routeToRemove = modeList.pop()
                else:
                    routeToRemove = None
                # Removes nodes from a mode's route
                if routeToRemove != None:
                    for i in theList:
                        if nextG.nodes[i]['mode']['type'] != 'walk':
                            if nextG.nodes[i]['mode']['details']['name'] == routeToRemove:
                                nextG.remove_node(i)
                else:
                    break
            
        resultsObj = {}
        resultsJson = {'routes': resultsObj}

        with perfTimer("convert nodes of each result into json format:"):
            count = 1
            for i in routesResultsList:
                nodeList = []
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

# Testing single directional Dijkstra's
@app.get("/test_yens")
def shortestPathTestf(src: str, dest: str):
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
            pathList = ox.k_shortest_paths(G, srcNode, destNode, 5, weight="weight")

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