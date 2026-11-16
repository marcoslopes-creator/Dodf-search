"""
setup_indices_vetoriais.py — Indices Atlas Search / Vector Search (autoEmbed)
=============================================================================
Cria/atualiza, de forma idempotente, os indices de busca a partir dos JSONs
do projeto (fonte unica de verdade), injetando modelo e quantizacao da CFG.

Automated Embedding (autoEmbed): o Atlas gera e mantem os vetores a partir do
campo de texto — a aplicacao nao envia embeddings. O indice define o modelo
dos documentos (voyage-4-large); as consultas usam um modelo menor da mesma
familia (voyage-4-lite) via `model` no $vectorSearch (asymmetric retrieval).

Indices gerenciados:
  - busca_vetorial (documentos.texto, autoEmbed + filtros de edicao)
  - cache_vetorial (cache_semantico.pergunta, autoEmbed)
  - busca_textual  (documentos, Atlas Search; campos de filtro de edicao)

Um indice legado (campo 'vector' com embeddings da aplicacao) nao pode ser
convertido para autoEmbed no mesmo path: ele e removido e recriado.

Uso:
  python setup_indices_vetoriais.py            (aplica CFG.VECTOR_QUANTIZATION)
  python setup_indices_vetoriais.py binary     (forca quantizacao binary)
  python setup_indices_vetoriais.py scalar
"""

import os
import sys
import json
import time

from pymongo.operations import SearchIndexModel

from config import get_db, CFG

_DIR = os.path.dirname(os.path.abspath(__file__))


def _carregar(nome_json: str) -> dict:
    with open(os.path.join(_DIR, nome_json), encoding="utf-8") as f:
        return json.load(f)


def _auto_embed_def(nome_json: str, field: str, model: str,
                    dim: int, quant: str) -> dict:
    """Definicao autoEmbed lida do JSON, com path/modelo/dim/quant da CFG."""
    defn = _carregar(nome_json)
    for campo in defn.get("fields", []):
        if campo.get("type") == "autoEmbed":
            campo["path"] = field
            campo["model"] = model
            campo["numDimensions"] = dim
            if quant and quant != "none":
                campo["quantization"] = quant
            else:
                campo.pop("quantization", None)
    return defn


def _info_existente(col, nome: str) -> dict:
    """Retorna o doc do indice (ou None) com sua definicao/status atuais."""
    try:
        for idx in col.list_search_indexes(nome):
            return idx
    except Exception as e:
        print(f"   (aviso ao listar '{nome}': {str(e)[:120]})", flush=True)
    return None


def _campo_principal(defn: dict) -> dict:
    for f in defn.get("fields", []):
        if f.get("type") in ("autoEmbed", "vector"):
            return f
    return {}


def _mesma_definicao(atual: dict, desejada: dict) -> bool:
    """Compara campos relevantes (tipo/path/modelo/dim/quant e filtros)."""
    a, d = _campo_principal(atual), _campo_principal(desejada)
    chaves = ("type", "path", "model", "numDimensions", "quantization", "similarity")
    if any(a.get(k) != d.get(k) for k in chaves):
        return False
    fa = sorted(f["path"] for f in atual.get("fields", []) if f.get("type") == "filter")
    fd = sorted(f["path"] for f in desejada.get("fields", []) if f.get("type") == "filter")
    return fa == fd


def aplicar_indice_vetorial(col, nome: str, defn: dict):
    """Cria, atualiza ou recria (legado vector -> autoEmbed) um indice."""
    info = _info_existente(col, nome)
    principal = _campo_principal(defn)
    desc = f"{principal.get('model')} | quant={principal.get('quantization', 'none')}"

    if info is None:
        print(f"   '{nome}': nao existe — criando ({desc})...", flush=True)
        col.create_search_index(
            model=SearchIndexModel(definition=defn, name=nome, type="vectorSearch"))
        print(f"   '{nome}': criacao submetida.", flush=True)
        return

    atual = info.get("latestDefinition", {})
    if _mesma_definicao(atual, defn):
        print(f"   '{nome}': ja esta como desejado ({desc}) — nada a fazer.", flush=True)
        return

    if _campo_principal(atual).get("type") == "vector":
        print(f"   '{nome}': indice legado (vector) — removendo e recriando "
              f"como autoEmbed ({desc})...", flush=True)
        col.drop_search_index(nome)
        _aguardar_remocao(col, nome)
        col.create_search_index(
            model=SearchIndexModel(definition=defn, name=nome, type="vectorSearch"))
        print(f"   '{nome}': recriacao submetida.", flush=True)
        return

    print(f"   '{nome}': definicao diferente — atualizando ({desc}; "
          f"rebuild em background)...", flush=True)
    col.update_search_index(nome, defn)
    print(f"   '{nome}': atualizacao submetida.", flush=True)


def aplicar_indice_textual(col, nome: str, defn: dict):
    """Cria ou atualiza o indice Atlas Search (busca textual)."""
    info = _info_existente(col, nome)
    if info is None:
        print(f"   '{nome}': nao existe — criando...", flush=True)
        col.create_search_index(
            model=SearchIndexModel(definition=defn, name=nome, type="search"))
        print(f"   '{nome}': criacao submetida.", flush=True)
        return
    atual = info.get("latestDefinition", {})
    if atual.get("mappings") == defn.get("mappings"):
        print(f"   '{nome}': mapeamentos ja atualizados — nada a fazer.", flush=True)
        return
    print(f"   '{nome}': mapeamentos diferentes — atualizando "
          f"(rebuild em background)...", flush=True)
    col.update_search_index(nome, defn)
    print(f"   '{nome}': atualizacao submetida.", flush=True)


def _aguardar_remocao(col, nome: str, timeout: int = 300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _info_existente(col, nome) is None:
            return True
        time.sleep(3)
    print(f"   '{nome}': timeout aguardando remocao.", flush=True)
    return False


def aguardar_pronto(col, nome: str, timeout: int = 600, carencia: int = 15):
    """Aguarda o indice ficar READY em todos os nos, com timeout.

    Apos um update, o indice antigo continua READY por alguns segundos antes
    do Atlas marcar BUILDING; por isso exige-se READY estavel por `carencia`
    segundos (e nenhum no em BUILDING/STALE em statusDetail).
    """
    t0 = time.time()
    pronto_desde = None
    while time.time() - t0 < timeout:
        info = _info_existente(col, nome)
        if info:
            status = info.get("status", "?")
            nos = [s.get("status") for s in info.get("statusDetail", [])]
            todos_ready = status == "READY" and all(s == "READY" for s in nos)
            if todos_ready:
                pronto_desde = pronto_desde or time.time()
                if time.time() - pronto_desde >= carencia:
                    print(f"   '{nome}': READY ({int(time.time()-t0)}s)", flush=True)
                    return True
            else:
                pronto_desde = None
            if status == "FAILED":
                print(f"   '{nome}': FAILED — verifique no Atlas.", flush=True)
                return False
        time.sleep(5)
    print(f"   '{nome}': timeout aguardando READY (segue em background).", flush=True)
    return False


def setup(quant: str = None):
    quant = (quant or CFG.VECTOR_QUANTIZATION or "none").lower()
    if quant not in ("none", "scalar", "binary"):
        print(f"Quantizacao invalida: {quant}. Use none|scalar|binary.")
        sys.exit(1)

    db = get_db()
    dim = CFG.VOYAGE_EMBEDDING_DIMENSION
    col_docs = db[CFG.MONGODB_COLLECTION]
    col_cache = db["cache_semantico"]
    print(f"\n{'='*60}")
    print(f"  INDICES (autoEmbed) — quantizacao={quant} | dim={dim}")
    print(f"  documentos: {CFG.VOYAGE_EMBEDDING_MODEL} | "
          f"consultas: {CFG.VOYAGE_QUERY_MODEL} | cache: {CFG.CACHE_EMBEDDING_MODEL}")
    print(f"{'='*60}\n", flush=True)

    vetoriais = [
        (col_docs, CFG.VECTOR_INDEX_NAME,
         _auto_embed_def("indice_busca_vetorial.json", CFG.VECTOR_FIELD,
                         CFG.VOYAGE_EMBEDDING_MODEL, dim, quant)),
        (col_cache, CFG.CACHE_INDEX_NAME,
         _auto_embed_def("indice_cache_vetorial.json", CFG.CACHE_VECTOR_FIELD,
                         CFG.CACHE_EMBEDDING_MODEL, dim, quant)),
    ]
    textual = (col_docs, "busca_textual", _carregar("indice_busca_textual.json"))

    print("1. Aplicando definicoes...", flush=True)
    for col, nome, defn in vetoriais:
        aplicar_indice_vetorial(col, nome, defn)
    aplicar_indice_textual(*textual)

    print("\n2. Aguardando indices ficarem prontos...", flush=True)
    for col, nome, _ in vetoriais + [textual]:
        aguardar_pronto(col, nome)

    print(f"\n{'='*60}\n  CONCLUIDO\n{'='*60}", flush=True)


if __name__ == "__main__":
    setup(sys.argv[1] if len(sys.argv) > 1 else None)
