"""
config.py — Configuracao Centralizada (Voyage 4 + MongoDB)
============================================================
- MongoClient unico com pool
- GridFS para armazenamento de PDFs
- Voyage 4 (voyage-4-large + rerank-2.5)
- Suporta provider 'atlas' (ai.mongodb.com) ou 'voyage' (api.voyageai.com)
"""

import os
import requests
from pymongo import MongoClient
from gridfs import GridFS
from dotenv import load_dotenv

load_dotenv()


class _Config:
    """Configuracoes lidas uma unica vez do .env."""

    # MongoDB
    MONGODB_URI = os.getenv("MONGODB_URI", "")
    MONGODB_DB = os.getenv("MONGODB_DB", "dodf_database")
    MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "documentos")

    # Voyage 4
    VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
    VOYAGE_API_PROVIDER = os.getenv("VOYAGE_API_PROVIDER", "atlas").lower()
    VOYAGE_EMBEDDING_MODEL = os.getenv("VOYAGE_EMBEDDING_MODEL", "voyage-4-large")
    VOYAGE_EMBEDDING_DIMENSION = int(os.getenv("VOYAGE_EMBEDDING_DIMENSION", "1024"))
    VOYAGE_EMBEDDING_BATCH = int(os.getenv("VOYAGE_EMBEDDING_BATCH", "128"))
    VOYAGE_TRUNCATION = os.getenv("VOYAGE_TRUNCATION", "true").lower() == "true"
    VOYAGE_RERANK_MODEL = os.getenv("VOYAGE_RERANK_MODEL", "rerank-2.5")

    # Reranking
    RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() == "true"
    RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "6"))
    RERANK_TRUNCATION = os.getenv("RERANK_TRUNCATION", "true").lower() == "true"

    # LLMs
    LLM_MODEL = os.getenv("LLM_MODEL", "gemma4:26b")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

    # Processamento
    PDF_FOLDER = os.getenv("PDF_FOLDER", "")
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1500"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "300"))
    PDF_SERVER_PORT = int(os.getenv("PDF_SERVER_PORT", "8502"))


CFG = _Config()


# =====================================================================
# MONGODB CLIENT (singleton com connection pool)
# =====================================================================

_client = None


def get_client() -> MongoClient:
    """MongoClient com connection pool compartilhado."""
    global _client
    if _client is None:
        _client = MongoClient(CFG.MONGODB_URI, maxPoolSize=20, minPoolSize=2)
    return _client


def get_db():
    return get_client()[CFG.MONGODB_DB]


def get_collection(nome: str = None):
    return get_db()[nome or CFG.MONGODB_COLLECTION]


def get_gridfs() -> GridFS:
    return GridFS(get_db())


# =====================================================================
# VOYAGE 4 — URLs e headers
# =====================================================================

def _api_urls() -> tuple:
    """(embed_url, rerank_url) baseado no provider."""
    if CFG.VOYAGE_API_PROVIDER == "atlas":
        return ("https://ai.mongodb.com/v1/embeddings",
                "https://ai.mongodb.com/v1/rerank")
    return ("https://api.voyageai.com/v1/embeddings",
            "https://api.voyageai.com/v1/rerank")


_voyage_headers = None


def _headers() -> dict:
    global _voyage_headers
    if _voyage_headers is None:
        if not CFG.VOYAGE_API_KEY:
            raise ValueError(
                "VOYAGE_API_KEY nao configurada. "
                "Defina no .env ou crie em https://dash.voyageai.com/ "
                "ou no MongoDB Atlas."
            )
        _voyage_headers = {
            "Authorization": f"Bearer {CFG.VOYAGE_API_KEY}",
            "Content-Type": "application/json"
        }
    return _voyage_headers


# =====================================================================
# EMBEDDINGS
# =====================================================================

def _build_payload(textos: list, input_type: str) -> dict:
    payload = {
        "input": textos,
        "model": CFG.VOYAGE_EMBEDDING_MODEL,
        "input_type": input_type,
    }
    if CFG.VOYAGE_EMBEDDING_DIMENSION:
        payload["output_dimension"] = CFG.VOYAGE_EMBEDDING_DIMENSION
    if CFG.VOYAGE_TRUNCATION:
        payload["truncation"] = True
    return payload


def gerar_embedding(texto: str) -> list:
    """Embedding de query unica."""
    embed_url, _ = _api_urls()
    payload = _build_payload([texto], "query")
    resp = requests.post(embed_url, headers=_headers(),
                         json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def gerar_embeddings_batch(textos: list, input_type: str = "document",
                            batch_size: int = None, timeout: int = 90) -> list:
    """Embeddings em lote para indexacao."""
    if not textos:
        return []
    embed_url, _ = _api_urls()
    bs = batch_size or CFG.VOYAGE_EMBEDDING_BATCH
    todos = []

    for i in range(0, len(textos), bs):
        lote = textos[i:i + bs]
        payload = _build_payload(lote, input_type)
        resp = requests.post(embed_url, headers=_headers(),
                             json=payload, timeout=timeout)
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda x: x["index"])
        todos.extend([d["embedding"] for d in data])
    return todos


# =====================================================================
# RERANKING
# =====================================================================

def rerancar(query: str, documentos: list, top_k: int = None) -> list:
    """Reordena documentos por relevancia usando rerank-2.5."""
    if not CFG.RERANK_ENABLED or not documentos:
        return documentos[:top_k or CFG.RERANK_TOP_K]

    if top_k is None:
        top_k = CFG.RERANK_TOP_K

    _, rerank_url = _api_urls()

    # Trunca textos longos antes de enviar
    textos = []
    for doc in documentos:
        txt = doc.get("texto", "")
        if len(txt) > 8000:
            txt = txt[:8000]
        textos.append(txt)

    try:
        payload = {
            "query": query,
            "documents": textos,
            "model": CFG.VOYAGE_RERANK_MODEL,
            "top_k": min(top_k, len(documentos)),
        }
        if CFG.RERANK_TRUNCATION:
            payload["truncation"] = True

        resp = requests.post(rerank_url, headers=_headers(),
                             json=payload, timeout=30)
        resp.raise_for_status()

        reordenados = []
        for r in resp.json()["data"]:
            doc = documentos[r["index"]].copy()
            doc["rerank_score"] = r["relevance_score"]
            reordenados.append(doc)
        return reordenados
    except Exception as e:
        print(f"[WARN] Rerank falhou: {str(e)[:100]}. Usando ordem original.")
        return documentos[:top_k]


# =====================================================================
# WRAPPER LANGCHAIN-COMPATIBLE
# =====================================================================

class _VoyageEmbeddingsWrapper:
    """Interface compativel com LangChain."""
    def embed_query(self, texto: str) -> list:
        return gerar_embedding(texto)

    def embed_documents(self, textos: list) -> list:
        return gerar_embeddings_batch(textos, input_type="document")


_embeddings = None


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = _VoyageEmbeddingsWrapper()
    return _embeddings


# =====================================================================
# HEALTH CHECK
# =====================================================================

def verificar_voyage_api() -> dict:
    """Testa as APIs Voyage. Retorna dict com status."""
    resultado = {"embed": False, "rerank": False, "erros": []}
    embed_url, rerank_url = _api_urls()

    try:
        resp = requests.post(embed_url, headers=_headers(),
                             json=_build_payload(["teste"], "query"), timeout=10)
        resp.raise_for_status()
        resultado["embed"] = True
    except Exception as e:
        resultado["erros"].append(f"embed: {str(e)[:200]}")

    try:
        resp = requests.post(rerank_url, headers=_headers(),
                             json={"query": "x", "documents": ["a", "b"],
                                   "model": CFG.VOYAGE_RERANK_MODEL, "top_k": 1},
                             timeout=10)
        resp.raise_for_status()
        resultado["rerank"] = True
    except Exception as e:
        resultado["erros"].append(f"rerank: {str(e)[:200]}")

    return resultado
