import os
import shutil
import time
from fastapi import FastAPI,WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from celery.result import AsyncResult
from pydantic import BaseModel
from celery import Celery
from redis_config import redis_client, redis_url
import sqlite3
import json
import asyncio
import uvicorn
import logging
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

active_connections = {}

app = FastAPI()

celery = Celery("osint_tasks", broker=redis_url)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

@app.middleware("http")
async def wrap_success_responses(request: Request, call_next):
    body = await request.body()
    print("📥 Raw body:", body)
    print("📋 Headers:", request.headers)
    try:
        response = await call_next(request)

        # Skip wrapping errors or already-JSON responses
        if response.status_code >= 400:
            return response

        # Only wrap JSON responses
        if hasattr(response, "media_type") and response.media_type == "application/json":
            body = b"".join([chunk async for chunk in response.body_iterator])
            response.body_iterator = iter([body])
            try:
                import json
                data = json.loads(body)
            except Exception:
                data = body.decode()

            # If already has 'success', leave it
            if isinstance(data, dict) and "success" in data:
                return response

            message = "Success"
            if isinstance(data, dict) and "message" in data:
                message = data.pop("message")

            # Wrap into standard format
            wrapped = {
                "success": True,
                "message": message,
                "data": data,
            }
            finalResponse = JSONResponse(content=wrapped, status_code=response.status_code)
            print("📥 Response:", finalResponse)
            return finalResponse
        return response
    except Exception as e:
        # Let global handler deal with unhandled errors
        raise e

@app.get("/action-map")
def get_action_map():
    with open("action_map.json") as f:
        action_map = json.load(f)

    return {'message': action_map}

@app.post("/upload-file")
async def upload_file(file: UploadFile = File(...)):
    try:
        # timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"{file.filename}"
        filepath = os.path.join('file_uploads', filename)

        os.makedirs("file_uploads", exist_ok=True)

        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

    return {"message": "File uploaded successfully", "filename": filename}

@app.post("/run/{source_name}")
def run_osint_task(source_name: str, req: RunRequest):
    task = celery.send_task("worker.run_tool", args=[source_name, req.query, req.node_id])
    return {"task_id": task.id}

@app.get("/task-result/{task_id}")
def get_task_result(task_id: str):
    task_result = celery.AsyncResult(task_id)
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

@app.exception_handler(Exception)
def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "There is a problem with our servers. Please try again later.",
            "code": "SERVER_ERROR"
        },
    )

@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    # If developer raises HTTPException(detail=...)
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": str(exc.detail)},
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)