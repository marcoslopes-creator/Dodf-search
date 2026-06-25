"""
backfill_atos.py — Popula a colecao 'atos' a partir dos chunks existentes
==========================================================================
Para bases ja indexadas: percorre os chunks de 'documentos' e extrai os
atos (regex + LLM hibrido) sem reler os PDFs originais.

Idempotente: processa por hash_arquivo e limpa os atos do arquivo antes
de reinserir. Pode rodar varias vezes com seguranca.

Uso:
  python backfill_atos.py            # processa todos os PDFs
  python backfill_atos.py --hash ABC # apenas um arquivo (por hash)
"""

import sys
import time

from config import get_db, get_collection, CFG
from extrator_atos import extrair_atos


def _atos_de_arquivo(hash_arq: str) -> int:
    """Extrai e grava os atos de um unico arquivo (por hash). Retorna qtd."""
    col_chunks = get_collection()
    col_atos = get_db()[CFG.ATOS_COLLECTION]

    col_atos.delete_many({"hash_arquivo": hash_arq})

    vistos, docs = set(), []
    cursor = col_chunks.find(
        {"hash_arquivo": hash_arq},
        {"texto": 1, "metadados.arquivo": 1, "metadados.pagina": 1},
    )
    for c in cursor:
        md = c.get("metadados", {})
        for ato in extrair_atos(c.get("texto", ""), md.get("arquivo", "?"),
                                md.get("pagina", "?"), hash_arq):
            chave = (ato["nome_normalizado"], ato["tipo_ato"], ato["pagina"])
            if chave in vistos:
                continue
            vistos.add(chave)
            docs.append(ato)

    if docs:
        col_atos.insert_many(docs)
    return len(docs)


def backfill(hash_unico: str = "") -> None:
    if not CFG.ATOS_EXTRACTION_ENABLED:
        print("ATOS_EXTRACTION_ENABLED=false — nada a fazer.")
        return

    col_chunks = get_collection()

    if hash_unico:
        hashes = [hash_unico]
    else:
        hashes = col_chunks.distinct("hash_arquivo")
        hashes = [h for h in hashes if h]

    if not hashes:
        print("Nenhum chunk encontrado em 'documentos'. Nada a fazer.")
        return

    print(f"\n{'='*60}")
    print(f"  BACK-FILL DE ATOS — {len(hashes)} arquivo(s)")
    print(f"{'='*60}\n")

    total_atos, t0 = 0, time.time()
    for i, h in enumerate(hashes, 1):
        nome = (col_chunks.find_one({"hash_arquivo": h},
                                    {"metadados.arquivo": 1}) or {})
        nome = nome.get("metadados", {}).get("arquivo", h[:12])
        try:
            n = _atos_de_arquivo(h)
            total_atos += n
            print(f"  [{i}/{len(hashes)}] {nome} — {n} atos", flush=True)
        except Exception as e:
            print(f"  [{i}/{len(hashes)}] {nome} — ERRO: {e}", flush=True)

    dt = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  CONCLUIDO: {total_atos} atos em {dt:.0f}s "
          f"({len(hashes)} arquivos)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    h = ""
    if len(sys.argv) >= 3 and sys.argv[1] == "--hash":
        h = sys.argv[2]
    backfill(h)
