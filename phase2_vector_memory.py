import os
import json
import chromadb
from sentence_transformers import SentenceTransformer

import argparse

CHROMA_DIR = "chroma_memory_db"
os.makedirs(CHROMA_DIR, exist_ok=True)

chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
print("[INIT] Loading embedding model for ChromaDB...")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

def get_collection_name(sandbox: bool = False) -> str:
    return "sre_incident_memory_shadow" if sandbox else "sre_incident_memory"

def get_chroma_collection(sandbox: bool = False):
    name = get_collection_name(sandbox)
    return chroma_client.get_or_create_collection(name=name)

def index_unified_dataset(sandbox: bool = False):
    collection = get_chroma_collection(sandbox)
    run_id = os.environ.get("SHADOW_RUN_ID", "default")
    filename = f"shadow_{run_id}_unified_master_dataset.json" if sandbox else "unified_master_dataset.json"
    dataset_path = os.path.join("frontend_data", filename)
    if not os.path.exists(dataset_path):
        print(f"[-] Error: '{dataset_path}' not found.")
        return

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    incident_list = dataset.get("incidents", []) if isinstance(dataset, dict) else dataset
    print(f"=== [Phase 2] Indexing {len(incident_list)} incidents into ChromaDB (Collection: {collection.name}) ===")

    for item in incident_list:
        # Extract from the nested JSON structure
        event_data = item.get("incident_event", {})
        telemetry = item.get("telemetry_evidence", {})

        incident_id = event_data.get("incident_id", "unknown")
        template = telemetry.get("log_cluster_template", "")
        service = event_data.get("target_service", "unknown")
        severity = event_data.get("severity", "UNKNOWN")
        priority_score = float(event_data.get("priority_score", 0.0))

        if not template:
            continue

        vector = embedding_model.encode(template).tolist()

        collection.upsert(
            ids=[str(incident_id)],
            embeddings=[vector],
            documents=[template],
            metadatas=[{
                "target_service": service,
                "severity": severity,
                "priority_score": priority_score
            }]
        )

    print(f"[+] Success! Indexed records into vector database collection '{collection.name}' at '{CHROMA_DIR}'.")

def query_similar_incident(new_log_template, top_k=2, sandbox: bool = False):
    collection = get_chroma_collection(sandbox)
    query_vector = embedding_model.encode(new_log_template).tolist()
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=top_k
    )
    return results

def record_remediation_outcome(incident_fingerprint: str, outcome: dict, sandbox: bool = True) -> None:
    """
    Store whether a proposed fix actually cleared the fault, keyed to the same
    (target_service, log_cluster_template) fingerprint used for indexing.
    Called by dynamic_execution_harness.py after each shadow execution.
    """
    collection = get_chroma_collection(sandbox)
    try:
        collection.update(
            ids=[incident_fingerprint],
            metadatas=[{
                "last_remediation_verified": outcome.get("fault_cleared", False),
                "last_remediation_timestamp": outcome.get("timestamp", "")
            }]
        )
    except Exception as e:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 2 Vector Memory Indexer")
    parser.add_argument("--sandbox", action="store_true", default=False, help="Index shadow dataset instead of production")
    args = parser.parse_args()

    index_unified_dataset(sandbox=args.sandbox)
    
    print("\n--- Testing Semantic Memory Lookup ---")
    test_query = "Failed to export traces over HTTP network timeout socket closed"
    match = query_similar_incident(test_query, sandbox=args.sandbox)
    print(f"Query: '{test_query}' (Sandbox={args.sandbox})")
    print(json.dumps(match, indent=4))