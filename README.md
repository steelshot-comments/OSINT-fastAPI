# FastAPI for OSINT Investigation app

## 🧱 Stack
- FastAPI + Gunicorn + UvicornWorker
- Celery + Redis (Upstash)
- Neo4j Aura (Free-tier graph DB)
- Render (Web + Worker)
- GitHub Actions (CI/CD)

## 🌐 Architecture
Client → Render Web Service → FastAPI (Gunicorn + Uvicorn)
↳ Celery Worker (Redis broker)
↳ Neo4j Aura Database

## 🧩 Features
- REST endpoints with background task handling
- Free-tier managed database and queue
- Automatic deployments via GitHub Actions
- HTTPS, logs, and health monitoring via Render

## 🏗️ Setup
1. Fork this repo
2. Create a **Render Web Service** and a **Worker Service**
3. Set the environment variables:
NEO4J_URI, NEO4J_USER, NEO4J_PASS, REDIS_URL
4. Deploy!

## 🧠 Example Endpoints
- `GET /` → Health check  
- `GET /api/users` → Count users in Neo4j  
- `POST /api/background-task` → Queue a Celery job
