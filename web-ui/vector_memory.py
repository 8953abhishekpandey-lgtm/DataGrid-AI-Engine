"""
vector_memory.py — Semantic pattern matching using local embeddings.
No API needed. sentence-transformers runs fully offline.
"""
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path

EMBED_MODEL = "all-MiniLM-L6-v2"  # 80MB, downloads once, then offline forever

class VectorMemory:
    def __init__(self, persist_dir: str = ".chroma"):
        self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBED_MODEL
        )
        self.client = chromadb.PersistentClient(path=persist_dir)
        
        # Two collections
        self.queries = self.client.get_or_create_collection(
            name="learned_queries",
            embedding_function=self.ef
        )
        self.docs = self.client.get_or_create_collection(
            name="document_chunks", 
            embedding_function=self.ef
        )
    
    def add_pattern(self, text: str, sql: str, chart_type: str, 
                    explanation: str, pattern_id: str):
        """Store a learned query pattern as a vector."""
        self.queries.upsert(
            ids=[pattern_id],
            documents=[text],
            metadatas=[{
                "sql": sql,
                "chart_type": chart_type,
                "explanation": explanation
            }]
        )
    
    def find_similar_query(self, text: str, threshold: float = 0.78):
        """
        Semantic search — finds similar queries even with different wording.
        'show active meters' matches 'list working meters' ← SequenceMatcher can't do this
        """
        results = self.queries.query(
            query_texts=[text],
            n_results=1
        )
        if not results["ids"][0]:
            return None
        
        # ChromaDB returns distance (lower = more similar), convert to similarity
        distance = results["distances"][0][0]
        similarity = 1 - distance  # cosine distance → similarity
        
        if similarity < threshold:
            return None
        
        meta = results["metadatas"][0][0]
        return {
            "sql":         meta["sql"],
            "chart_type":  meta["chart_type"],
            "explanation": meta["explanation"],
            "confidence":  similarity,
            "matched_text": results["documents"][0][0]
        }
    
    def add_document_chunks(self, doc_name: str, text: str, 
                             chunk_size: int = 500):
        """Split document into chunks and store as vectors."""
        words = text.split()
        chunks = [
            " ".join(words[i:i+chunk_size]) 
            for i in range(0, len(words), chunk_size)
        ]
        
        self.docs.upsert(
            ids=[f"{doc_name}_chunk_{i}" for i in range(len(chunks))],
            documents=chunks,
            metadatas=[{"doc_name": doc_name, "chunk_idx": i} 
                       for i in range(len(chunks))]
        )
    
    def search_documents(self, query: str, n_results: int = 3) -> list[str]:
        """Find most relevant document chunks for a question."""
        if self.docs.count() == 0:
            return []
        
        results = self.docs.query(
            query_texts=[query],
            n_results=min(n_results, self.docs.count())
        )
        return results["documents"][0]  # list of relevant text chunks

vector_memory = VectorMemory()