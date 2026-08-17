from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from ksp import getJeepRoutes, getTrikeTerminalsList, getKShortestPathsJson

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:8080'],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"]
)

@app.get("/jeep_routes")
def get_jeep_routes():
    try:
        jeepRoutesList = getJeepRoutes()
        return {"routes": jeepRoutesList}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal Server Error.")

@app.get("/trike_terminals_list")
def get_trike_terminals():
    try:
        trikeTerminalsList = getTrikeTerminalsList()
        return {"terminalList": trikeTerminalsList}
    except Exception:
        raise HTTPException(status_code=500, detail="Internal Server Error.")

@app.get("/k_shortest_paths")
def get_ksp_results(src: str, dest: str, algo:str='astar', traffic:bool=False):
    try:
        results = getKShortestPathsJson(src, dest, algo, traffic)
        return results
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=e)