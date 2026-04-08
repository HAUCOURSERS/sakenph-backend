from fastapi import FastAPI

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