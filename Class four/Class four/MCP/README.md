# Mini MCP Server (FastAPI)

Minimal tool server exposing two HTTP endpoints:

- `GET /tools` – list available tools
- `POST /call` – invoke a tool with `{"tool": "...", "args": {...}}`

## Run locally

```bash
pip install -r requirements.txt
uvicorn fast_api_v1:app --reload --port 8787
```

Test:

```bash
curl http://127.0.0.1:8787/tools
curl -X POST http://127.0.0.1:8787/call \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_market_data","args":{"symbol":"NQ"}}'
```

Interactive docs: http://127.0.0.1:8787/docs

## Deploy to Render

This repo includes `render.yaml`, so the fastest path is:

1. Push this folder to a GitHub repository.
2. In Render: **New + → Blueprint**, pick the repo, click **Apply**.
   - Render reads `render.yaml` and creates the web service automatically.
3. Alternatively create a **Web Service** manually with:
   - Language: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn fast_api_v1:app --host 0.0.0.0 --port $PORT`
   - Health Check Path: `/tools`

After deploy, the API is at `https://<service-name>.onrender.com`
(`/tools`, `/call`, `/docs`).

Point the n8n HTTP Request node at `https://<service-name>.onrender.com/call`
instead of `http://127.0.0.1:8787/call`.

Note: on Render's free plan the service spins down after ~15 minutes of
inactivity and takes ~30–60 s to cold start on the next request.
