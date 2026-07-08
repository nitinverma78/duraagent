import os
import tempfile
import shutil
import uuid
from typing import Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from duraagent.agent import Agent
from duraagent.harness import SandboxRunner
from duraagent.llm import get_llm_client
from duraagent.state_store import SQLiteStateStore
from duraagent.metrics import MetricsTracker

app = FastAPI(
    title="DuraAgent API",
    description="A self-evolving agentic code review engine.",
    version="1.0.0"
)

# Shared store for the demo
DB_PATH = os.path.join(tempfile.gettempdir(), "duraagent_api.db")
store = SQLiteStateStore(DB_PATH)

class ReviewRequest(BaseModel):
    project_path: str

@app.get("/")
def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "DuraAgent API is running. Visit /docs for the Swagger UI."}

@app.post("/api/review")
def review_codebase(req: ReviewRequest) -> Dict[str, Any]:
    """
    Run DuraAgent on a local codebase path.
    """
    if not os.path.exists(req.project_path):
        raise HTTPException(status_code=404, detail="Project path not found")
        
    run_id = f"api-run-{uuid.uuid4().hex[:8]}"
    llm = get_llm_client()
    runner = SandboxRunner()
    agent = Agent(store=store, llm=llm, runner=runner)
    
    try:
        result = agent.review_and_fix(req.project_path, run_id=run_id)
        metrics = MetricsTracker(store).get_workflow_metrics(run_id)
        return {
            "run_id": run_id,
            "status": "completed",
            "result": result,
            "metrics": metrics
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
