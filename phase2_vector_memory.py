import os
import json
import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_DIR = "chroma_memory_db"
os.makedirs(CHROMA_DIR, exist_ok=True)

chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
print("[INIT] Loading embedding model for ChromaDB...")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

collection = chroma_client.get_or_create_collection(name="sre_incident_memory")

def index_unified_dataset():
    dataset_path = os.path.join("frontend_data", "unified_master_dataset.json")
    if not os.path.exists(dataset_path):
        print(f"[-] Error: '{dataset_path}' not found.")
        return

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    incident_list = dataset.get("incidents", []) if isinstance(dataset, dict) else dataset
    print(f"=== [Phase 2] Indexing {len(incident_list)} incidents into ChromaDB ===")

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

    print(f"[+] Success! Indexed records into vector database at '{CHROMA_DIR}'.")

def query_similar_incident(new_log_template, top_k=2):
    query_vector = embedding_model.encode(new_log_template).tolist()
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=top_k
    )
    return results

if __name__ == "__main__":
    index_unified_dataset()
    
    print("\n--- Testing Semantic Memory Lookup ---")
    test_query = "Failed to export traces over HTTP network timeout socket closed"
    match = query_similar_incident(test_query)
    print(f"Query: '{test_query}'")
    print(json.dumps(match, indent=4))