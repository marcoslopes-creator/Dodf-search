"""
reforco_atos.py — Reforco de atos via LLM sobre chunks residuais (V2 #4)
========================================================================
Passada paralela e resumivel sobre os chunks que TEM gatilho de ato
(nomea/exoner/design/dispens) mas onde o regex nao extraiu nada — os
~5.3k "residuais". Para cada um, chama o LLM e grava na colecao 'atos'.

Resumivel: marca cada chunk processado com o campo 'reforco_llm' (data);
re-execucoes pulam o que ja foi feito. Idempotente: upsert por
(hash_arquivo, nome_normalizado, tipo_ato, pagina).

Uso:
  python reforco_atos.py                # todos os chunks residuais
  python reforco_atos.py --limite 50    # amostra (teste)
  python reforco_atos.py --hash ABC     # apenas um arquivo (por hash)
  python reforco_atos.py --reset        # limpa marcadores e recomeca
"""

import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import get_db, get_collection, CFG
from extrator_atos import extrair_regex, extrair_llm, _TRIGGER

# Candidatos no Mongo: chunks com gatilho ainda nao reforcados.
_TRIGGER_MONGO = "nomea|exoner|design|dispens|NOMEAR|EXONERAR|DESIGNAR|DISPENSAR"


def _processar_chunk(doc: dict) -> tuple:
    """Worker (thread): regex barato; LLM so quando regex falha. Retorna
    (chunk_id, lista_de_atos)."""
    texto = doc.get("texto", "")
    md = doc.get("metadados", {})
    arquivo, pagina = md.get("arquivo", "?"), md.get("pagina", "?")
    hash_arq = doc.get("hash_arquivo", "")

    atos = extrair_regex(texto, arquivo, pagina, hash_arq)
    if not atos and _TRIGGER.search(texto):
        atos = extrair_llm(texto, arquivo, pagina, hash_arq)
    return doc["_id"], atos


def _gravar(col_atos, col_chunks, chunk_id, atos) -> int:
    """Upsert idempotente dos atos + marcacao do chunk (resumivel)."""
    novos = 0
    for ato in atos:
        chave = {
            "hash_arquivo": ato["hash_arquivo"],
            "nome_normalizado": ato["nome_normalizado"],
            "tipo_ato": ato["tipo_ato"],
            "pagina": ato["pagina"],
        }
        res = col_atos.update_one(chave, {"$setOnInsert": ato}, upsert=True)
        if res.upserted_id is not None:
            novos += 1
    col_chunks.update_one({"_id": chunk_id},
                          {"$set": {"reforco_llm": datetime.now()}})
    return novos


def reforcar(hash_unico: str = "", limite: int = 0, reset: bool = False) -> None:
    if not (CFG.ATOS_EXTRACTION_ENABLED and CFG.ATOS_LLM_ENABLED):
        print("ATOS_EXTRACTION_ENABLED/ATOS_LLM_ENABLED=false — nada a fazer.")
        return
    if not CFG.CLAUDE_DISPONIVEL:
        print("GROVE_API_KEY/ANTHROPIC_API_KEY ausentes — reforco por LLM indisponivel.")
        return

    col_chunks = get_collection()
    col_atos = get_db()[CFG.ATOS_COLLECTION]

    filtro = {"texto": {"$regex": _TRIGGER_MONGO, "$options": "i"}}
    if hash_unico:
        filtro["hash_arquivo"] = hash_unico

    if reset:
        n = col_chunks.update_many(
            filtro, {"$unset": {"reforco_llm": ""}}).modified_count
        print(f"Reset: {n} marcadores 'reforco_llm' removidos.")

    filtro["reforco_llm"] = {"$exists": False}

    proj = {"texto": 1, "hash_arquivo": 1,
            "metadados.arquivo": 1, "metadados.pagina": 1}
    cursor = col_chunks.find(filtro, proj)
    if limite > 0:
        cursor = cursor.limit(limite)
    docs = list(cursor)

    if not docs:
        print("Nenhum chunk residual pendente. Nada a fazer.")
        return

    print(f"\n{'='*60}")
    print(f"  REFORCO DE ATOS (LLM) — {len(docs)} chunk(s) | "
          f"{CFG.ATOS_REFORCO_WORKERS} thread(s)")
    print(f"{'='*60}\n")

    total_atos = total_llm = feitos = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=CFG.ATOS_REFORCO_WORKERS) as ex:
        futs = {ex.submit(_processar_chunk, d): d for d in docs}
        for fut in as_completed(futs):
            feitos += 1
            try:
                chunk_id, atos = fut.result()
            except Exception as e:
                print(f"  [{feitos}/{len(docs)}] ERRO worker: {e}", flush=True)
                continue
            novos = _gravar(col_atos, col_chunks, chunk_id, atos)
            total_atos += novos
            if atos:
                total_llm += 1
            if feitos % 50 == 0 or feitos == len(docs):
                print(f"  [{feitos}/{len(docs)}] +{total_atos} atos "
                      f"({total_llm} chunks renderam atos)", flush=True)

    dt = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  CONCLUIDO: {total_atos} atos novos de {len(docs)} chunks "
          f"em {dt:.0f}s")
    print(f"{'='*60}\n")


def _parse_args(argv):
    h, limite, reset = "", 0, False
    i = 1
    while i < len(argv):
        if argv[i] == "--hash" and i + 1 < len(argv):
            h = argv[i + 1]; i += 2
        elif argv[i] == "--limite" and i + 1 < len(argv):
            limite = int(argv[i + 1]); i += 2
        elif argv[i] == "--reset":
            reset = True; i += 1
        else:
            i += 1
    return h, limite, reset


if __name__ == "__main__":
    h, limite, reset = _parse_args(sys.argv)
    reforcar(h, limite, reset)
