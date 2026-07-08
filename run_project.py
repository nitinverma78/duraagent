import json
import logging
import os
import sys

from duraagent.agent import Agent
from duraagent.state_store import SQLiteStateStore

logging.basicConfig(level=logging.INFO)

def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Warning: ANTHROPIC_API_KEY is not set. The agent will run in Mock mode.")
    
    project_path = sys.argv[1] if len(sys.argv) > 1 else "./sample_project"
    print(f"Running DuraAgent review on: {project_path}")
    
    # Initialize the state store
    store = SQLiteStateStore("duraagent.db")
    
    # Run the agent
    agent = Agent(store)
    result = agent.review_and_fix(project_path)
    
    print("\n=== AGENT RESULTS ===")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
