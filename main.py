from fastapi import FastAPI, HTTPException
import networkx as nx
import time
from contextlib import contextmanager
import osmnx as ox
import geopandas as gpd
import numpy as np
import os
import json
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
with open(f"color.json") as f:
    colors = json.load(f)

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
