import os
import shutil
import time
from fastapi import FastAPI,WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from celery.result import AsyncResult
from pydantic import BaseModel
from worker import run_tool, celery
from redis_config import redis_client
import sqlite3
import json
import asyncio
import uvicorn

active_connections = {}

app = FastAPI()

class RunRequest(BaseModel):
    query: str
    node_id: str

def fetch_results():
    conn = sqlite3.connect("osint_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM osint_results ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        print(row)
        results.append({
            "id": row[0],
            "source": row[1],
            "query": row[2],
            "result": json.loads(row[3]),  # Parse stored JSON result
            "timestamp": row[4]
        })
    return results

# Create root endpoint
@app.get("/")
def read_root():
    # explain the routes
    return {
        "message": "Welcome to the OSINT Data Ingestion API!",
        "routes": {
            "/run/{source_name}/{query}": "Run an OSINT task with the specified source and query.",
            "/result/{task_id}": "Get the result of a task by its ID.",
            "/results": "Fetch all results from the database.",
            "/ws/transforms/{node_id}": "WebSocket endpoint for transform updates.",
            "/action-map": "ahhaha"
        }
    }

@app.get("/action-map")
def get_action_map():
    with open("action_map.json") as f:
        action_map = json.load(f)

    return JSONResponse(content=action_map)

@app.post("/upload-file")
async def upload_file(file: UploadFile = File(...)):
    try:
        # timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"{file.filename}"
        filepath = os.path.join('file_uploads', filename)

        os.makedirs("file_uploads", exist_ok=True)  # Ensure folder exists

        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

    return JSONResponse(content={"message": "File uploaded successfully", "filename": filename})

@app.post("/run/{source_name}")
def run_osint_task(source_name: str, req: RunRequest):
    task = run_tool.delay(source_name, req.query, req.node_id)
    return {"task_id": task.id}

@app.get("/task-result/{task_id}")
def get_task_result(task_id: str):
    task_result = AsyncResult(task_id, app=celery)
    if task_result.ready():
        return {"status": "SUCCESS", "result": task_result.result}
    return {"status": "pending"}

@app.get("/task-results")
def get_results():
    return fetch_results()

@app.delete("/delete-task-result/{task_id}")
def delete_task(task_id: str):
    conn = sqlite3.connect("osint_data.db")
    cursor = conn.cursor()
    query = "DELETE FROM osint_results where id = ?"
    cursor.execute(query, (task_id, ))
    conn.commit()
    conn.close()
    return {"SUCCESS"}

@app.websocket("/ws/transforms/{node_id}")
async def transform_updates(websocket: WebSocket, node_id: str):
    await websocket.accept()
    pubsub = redis_client.pubsub()
    
    await asyncio.to_thread(pubsub.subscribe, "transform_updates")

    try:
        while True:
            message = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0)
            if message and message["type"] == "message":
                payload = json.loads(message["data"])
                if payload.get("status") == "completed":
                    await websocket.close()
                    break
                if payload["node_id"] == node_id:
                    await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        await asyncio.to_thread(pubsub.unsubscribe, "transform_updates")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)