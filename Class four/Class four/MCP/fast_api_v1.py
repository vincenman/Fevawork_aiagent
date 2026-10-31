# -*- coding: utf-8 -*-
"""
Created on Fri Sep 26 09:46:51 2025

@author: user
"""

from fastapi import FastAPI, Request, HTTPException

app = FastAPI(title="Mini MCP Server")

# --- Minimal tool registry: name -> callable ---
def tool_get_market_data(args):
    symbol = args.get("symbol", "NQ")
    price = 100.0 + (hash(symbol) % 5000) / 100.0
    return {"symbol": symbol, "last": round(price, 2)}

def tool_place_order(args):
    # No real side effects here?ust echo back what would be placed
    required = ["symbol", "side", "quantity", "order_type"]
    missing = [k for k in required if k not in args]
    if missing:
        raise HTTPException(400, f"Missing fields: {missing}")
    return {
        "status": "submitted",
        "order_id": "PAPER-123456",
        **args,
    }

TOOLS = {
    "get_market_data": tool_get_market_data,
    "place_order": tool_place_order,
}

@app.get("/tools")
def list_tools():
    # Minimal ?apabilities??listing
    return [{"name": name, "description": fn.__name__} for name, fn in TOOLS.items()]

@app.post("/call")
async def call_tool(req: Request):
    body = await req.json()
    tool = body.get("tool")
    args = body.get("args", {}) or {}
    if tool not in TOOLS:
        raise HTTPException(404, f"Unknown tool: {tool}")
    return TOOLS[tool](args)



if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
