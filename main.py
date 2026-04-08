from fastapi import FastAPI
import importlib
importlib.reload(ox)
import networkx as nx
import time
from contextlib import contextmanager
import osmnx as ox
import geopandas as gpd

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

# Testing single directional Dijkstra's
@app.get("/shortest_path_test")
def shortestPathTest():

    @contextmanager
    def perfTimer(action=""):
        start = time.perf_counter()
        yield
        end = time.perf_counter()
        print(f"Elapsed time to {action}: {round(end - start, 2)}s")

    with perfTimer("read nodes and edges of mabalacat+angeles City"):
        nodes = gpd.read_file("mabalacatAngeles/mabalacatAngeles_nodes.geojson")
        edges = gpd.read_file("mabalacatAngeles/mabalacatAngeles_edges.geojson")

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
