from fastapi import FastAPI
import uvicorn
import multiprocessing
import time

def run_hermes():
    app = FastAPI()
    @app.get("/v1/models")
    def models():
        return {"data": [{"id": "hermes"}]}
    @app.post("/v1/chat/completions")
    def chat():
        return {"choices": [{"message": {"content": "Hello from Hermes Desktop Mock!"}}]}
    uvicorn.run(app, host="127.0.0.1", port=8642)

def run_openclaw():
    app = FastAPI()
    @app.get("/health")
    def health():
        return {"status": "ok"}
    @app.post("/action")
    def action():
        return {"result": "Action executed by OpenClaw old version."}
    uvicorn.run(app, host="127.0.0.1", port=8643)

if __name__ == "__main__":
    p1 = multiprocessing.Process(target=run_hermes)
    p2 = multiprocessing.Process(target=run_openclaw)
    p1.start()
    p2.start()
    while True:
        time.sleep(1)
