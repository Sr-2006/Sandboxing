import os
import json
import chromadb
from fastmcp import FastMCP
from sentence_transformers import SentenceTransformer

# Initialize the MCP Server (Binding to 0.0.0.0 for Cloudflare Tunneling)
mcp = FastMCP("Auto-SRE Phase 2 Memory Agent")

# Connect to the local Vector Database
CHROMA_DIR = "chroma_memory_db"
try:
    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = chroma_client.get_collection(name="sre_incident_memory")
    embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
except Exception as e:
    print(f"Failed to load memory engine. Did you run phase2_vector_memory.py first? Error: {e}")

@mcp.tool()
def search_historical_incidents(error_log: str, top_k: int = 2) -> str:
    """
    Query the ChromaDB historical incident memory to find exact or semantically similar past errors.
    Use this tool whenever a new error log is detected to see if it has happened before.
    """
    query_vector = embedding_model.encode(error_log).tolist()
    
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=top_k
    )
    
    formatted_results = []
    for i in range(len(results["ids"][0])):
        formatted_results.append({
            "historical_incident_id": results["ids"][0][i],
            "similarity_distance": round(results["distances"][0][i], 3),
            "original_log_template": results["documents"][0][i],
            "service": results["metadatas"][0][i]["target_service"],
            "severity": results["metadatas"][0][i]["severity"]
        })
        
    return json.dumps(formatted_results, indent=2)

if __name__ == "__main__":
    print("=== [Phase 2] Starting FastMCP Diagnostic Server ===")
    print("[+] Waiting for connection from Phase 3 (Laptop C) via Cloudflare...")
    
    # Run the server on port 8000 as mandated by Section 2 of the Architecture doc
    mcp.run(transport='sse', host='0.0.0.0', port=8000)