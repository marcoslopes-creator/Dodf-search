"""
config.py — Configuracao Centralizada (Voyage 4 + MongoDB)
============================================================
- MongoClient unico com pool
- GridFS para armazenamento de PDFs
- Voyage 4 via Atlas Automated Embedding (autoEmbed):
    * documentos indexados com voyage-4-large (servidor, na indexacao)
    * consultas embedadas com voyage-4-lite (servidor, no $vectorSearch)
- rerank-2.5 via API (provider 'atlas' ai.mongodb.com ou 'voyage')
"""

import os
import requests
from pymongo import MongoClient
from gridfs import GridFS
from dotenv import load_dotenv

# Variaveis do Claude Code exportadas no shell (~/.zshrc) sao lidas
# automaticamente pelo SDK da Anthropic e desviariam as chamadas da aplicacao
# (base_url/token/alias de modelo). A fonte de configuracao do app e o .env.
for _v in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL",
           "ANTHROPIC_API_KEY", "ANTHROPIC_DEFAULT_OPUS_MODEL",
           "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
           "ANTHROPIC_SMALL_FAST_MODEL"):
    os.environ.pop(_v, None)

load_dotenv(override=True)


class _Config:
    """Configuracoes lidas uma unica vez do .env."""

    # MongoDB
    MONGODB_URI = os.getenv("MONGODB_URI", "")
    MONGODB_DB = os.getenv("MONGODB_DB", "dodf_database")
    MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "documentos")

    # Voyage 4
    VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
    VOYAGE_API_PROVIDER = os.getenv("VOYAGE_API_PROVIDER", "atlas").lower()
    # Modelo dos documentos (definido no indice autoEmbed; muda => reindexa)
    VOYAGE_EMBEDDING_MODEL = os.getenv("VOYAGE_EMBEDDING_MODEL", "voyage-4-large")
    # Modelo das consultas (asymmetric retrieval: mesma familia Voyage 4,
    # espaco vetorial compativel, menor latencia/custo por pergunta)
    VOYAGE_QUERY_MODEL = os.getenv("VOYAGE_QUERY_MODEL", "voyage-4-lite")
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
    # Claude: via Grove (gateway corporativo, rota compativel com a API
    # Anthropic) quando GROVE_API_KEY esta definido; senao API direta.
    GROVE_BASE_URL = os.getenv("GROVE_BASE_URL",
                               "https://ai-gateway.corp.mongodb.com").rstrip("/")
    GROVE_API_KEY = os.getenv("GROVE_API_KEY", "")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    CLAUDE_PROVEDOR = "Grove" if GROVE_API_KEY else "Anthropic"
    CLAUDE_DISPONIVEL = bool(GROVE_API_KEY or ANTHROPIC_API_KEY)
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-pro-preview")
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
    MISTRAL_OCR_MODEL = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")

    # Processamento
    PDF_FOLDER = os.getenv("PDF_FOLDER", "")
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1500"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "300"))
    PDF_SERVER_PORT = int(os.getenv("PDF_SERVER_PORT", "8502"))

    # Ingestao paralela e resumivel (V2 #1)
    INGEST_WORKERS = int(os.getenv("INGEST_WORKERS", "4"))

    # Indice vetorial autoEmbed / quantizacao (V2 #2)
    # VECTOR_FIELD e o campo de TEXTO que o Atlas embeda (nao um array).
    VECTOR_INDEX_NAME = os.getenv("VECTOR_INDEX_NAME", "busca_vetorial")
    VECTOR_FIELD = os.getenv("VECTOR_FIELD", "texto")
    # none | scalar | binary. none = fidelidade total (float32); a base atual
    # (~52k vetores, ~210 MB) cabe em memoria sem quantizar.
    VECTOR_QUANTIZATION = os.getenv("VECTOR_QUANTIZATION", "none").lower()
    VECTOR_NUM_CANDIDATES = int(os.getenv("VECTOR_NUM_CANDIDATES", "150"))
    # Pre-filtros do $vectorSearch (data/edicao/arquivo extraidos da pergunta)
    VECTOR_PREFILTER_ENABLED = os.getenv("VECTOR_PREFILTER_ENABLED", "true").lower() == "true"
    # Busca hibrida via $rankFusion (MongoDB >= 8.1): $search + $vectorSearch
    # fundidos no servidor por Reciprocal Rank Fusion, em uma unica consulta.
    # false = fusao no cliente (duas consultas em paralelo + intercalacao).
    RANKFUSION_ENABLED = os.getenv("RANKFUSION_ENABLED", "true").lower() == "true"
    RANKFUSION_PESO_TEXTUAL = float(os.getenv("RANKFUSION_PESO_TEXTUAL", "1"))
    RANKFUSION_PESO_SEMANTICO = float(os.getenv("RANKFUSION_PESO_SEMANTICO", "1"))
    # Cache semantico: autoEmbed sobre o texto da pergunta (modelo leve)
    CACHE_INDEX_NAME = os.getenv("CACHE_INDEX_NAME", "cache_vetorial")
    CACHE_VECTOR_FIELD = os.getenv("CACHE_VECTOR_FIELD", "pergunta")
    CACHE_EMBEDDING_MODEL = os.getenv("CACHE_EMBEDDING_MODEL", "voyage-4-lite")

    # Latencia / concorrencia (V2 #3)
    MONGO_MAX_POOL_SIZE = int(os.getenv("MONGO_MAX_POOL_SIZE", "100"))
    MONGO_MIN_POOL_SIZE = int(os.getenv("MONGO_MIN_POOL_SIZE", "5"))
    MONGO_SERVER_SELECTION_TIMEOUT_MS = int(
        os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000"))
    # Cache semantico. Com autoEmbed a pergunta armazenada e embedada como
    # "document" e a consulta como "query" (assimetrico): texto identico pontua
    # ~0.85, nao 1.0. Calibrado: parafrases >= 0.84; mesma pergunta com outro
    # ano/orgao <= 0.80.
    CACHE_SIMILARITY = float(os.getenv("CACHE_SIMILARITY", "0.82"))
    CACHE_NUM_CANDIDATES = int(os.getenv("CACHE_NUM_CANDIDATES", "10"))
    # Rerank condicional: pula o rerank (1 ida a API) quando o melhor score
    # semantico ja e >= este limiar (vencedor claro). 0 = sempre rerankear.
    RERANK_SKIP_SCORE = float(os.getenv("RERANK_SKIP_SCORE", "0"))

    # Extracao estruturada de atos (Fase 1)
    ATOS_COLLECTION = os.getenv("ATOS_COLLECTION", "atos")
    ATOS_EXTRACTION_ENABLED = os.getenv("ATOS_EXTRACTION_ENABLED", "true").lower() == "true"
    ATOS_LLM_ENABLED = os.getenv("ATOS_LLM_ENABLED", "true").lower() == "true"
    # Reforco de atos via LLM sobre chunks residuais (V2 #4)
    ATOS_REFORCO_WORKERS = int(os.getenv("ATOS_REFORCO_WORKERS", "4"))

    # OCR de fallback (so para paginas que falham na extracao de texto)
    OCR_ENABLED = os.getenv("OCR_ENABLED", "false").lower() == "true"
    OCR_PROVIDER = os.getenv("OCR_PROVIDER", "gemini").lower()  # gemini | mistral
    OCR_MIN_CHARS = int(os.getenv("OCR_MIN_CHARS", "120"))
    OCR_DPI = int(os.getenv("OCR_DPI", "200"))
    OCR_MAX_PAGES_POR_PDF = int(os.getenv("OCR_MAX_PAGES_POR_PDF", "50"))


CFG = _Config()


# =====================================================================
# LLM CLAUDE (Grove ou Anthropic direto) — ponto unico de instanciacao
# =====================================================================

def criar_claude(**kwargs):
    """ChatAnthropic apontando para o Grove (se configurado) ou para a API
    direta. kwargs: temperature, max_tokens, timeout, max_retries..."""
    from langchain_anthropic import ChatAnthropic
    if CFG.GROVE_API_KEY:
        return ChatAnthropic(model=CFG.ANTHROPIC_MODEL, api_key=CFG.GROVE_API_KEY,
                             base_url=f"{CFG.GROVE_BASE_URL}/anthropic", **kwargs)
    return ChatAnthropic(model=CFG.ANTHROPIC_MODEL, api_key=CFG.ANTHROPIC_API_KEY,
                         **kwargs)


# =====================================================================
# MONGODB CLIENT (singleton com connection pool)
# =====================================================================

_client = None


def get_client() -> MongoClient:
    """MongoClient com connection pool compartilhado (tunado para concorrencia)."""
    global _client
    if _client is None:
        _client = MongoClient(
            CFG.MONGODB_URI,
            maxPoolSize=CFG.MONGO_MAX_POOL_SIZE,
            minPoolSize=CFG.MONGO_MIN_POOL_SIZE,
            serverSelectionTimeoutMS=CFG.MONGO_SERVER_SELECTION_TIMEOUT_MS,
            retryWrites=True,
            retryReads=True,
            appname="dodf-search",
        )
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
# EMBEDDINGS (API direta — apenas diagnostico/health check; a busca e a
# ingestao usam Automated Embedding no Atlas, sem chamar esta API)
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
