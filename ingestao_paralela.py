"""
ingestao_paralela.py — Ingestao paralela e resumivel de PDFs (V2 #1)
=====================================================================
Substitui a varredura sequencial do monitor_pasta por um pool de
processos. Cada worker processa um PDF de forma independente; a
deduplicacao por hash (processar_pdf_bytes -> _ja_processado) torna a
ingestao naturalmente RESUMIVEL: reexecutar pula o que ja foi feito.

Uso:
  python ingestao_paralela.py                 (ingere PDF_FOLDER)
  python ingestao_paralela.py /caminho/pasta  (ingere pasta especifica)
  python ingestao_paralela.py --forcar        (reprocessa in-place)
"""

import os
import sys
import glob
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from config import CFG, get_db, get_collection
from processar_pdf import processar_pdf_bytes, _hash_bytes


def _listar_pdfs(pasta: str) -> list:
    return sorted(glob.glob(os.path.join(pasta, "*.pdf")))


def _worker(caminho: str, origem: str, forcar: bool) -> dict:
    """Executado em processo separado. Le, (opcional) limpa e processa 1 PDF."""
    nome = os.path.basename(caminho)
    t0 = time.time()
    try:
        with open(caminho, "rb") as f:
            data = f.read()
        hash_md5 = _hash_bytes(data)

        if forcar:
            get_collection().delete_many({"hash_arquivo": hash_md5})
            get_db()["pdfs"].delete_one({"hash_md5": hash_md5})

        r = processar_pdf_bytes(nome, data, origem=origem)
        r["nome"] = nome
        r["dt"] = time.time() - t0
        return r
    except Exception as e:  # nunca derruba o pool por causa de 1 arquivo
        return {"status": "erro", "nome": nome, "erro": str(e)[:200],
                "dt": time.time() - t0}


def ingerir_pasta(pasta: str = None, workers: int = None,
                  forcar: bool = False, origem: str = "ingestao_paralela") -> dict:
    """Ingere todos os PDFs da pasta usando um pool de processos."""
    pasta = pasta or CFG.PDF_FOLDER
    if not pasta or not os.path.isdir(pasta):
        print(f"ERRO: Pasta nao encontrada: {pasta}", flush=True)
        return {"ok": 0, "erros": 0, "pulados": 0}

    workers = workers or CFG.INGEST_WORKERS
    pdfs = _listar_pdfs(pasta)
    total = len(pdfs)

    print(f"\n{'='*60}", flush=True)
    print(f"  INGESTAO PARALELA — {total} PDF(s) | {workers} workers", flush=True)
    print(f"  Pasta: {pasta} | forcar={forcar}", flush=True)
    print(f"  OCR_ENABLED={CFG.OCR_ENABLED} | provider={CFG.OCR_PROVIDER}", flush=True)
    print(f"{'='*60}\n", flush=True)

    if not pdfs:
        return {"ok": 0, "erros": 0, "pulados": 0}

    t0 = time.time()
    ok = erros = pulados = chunks_total = atos_total = 0
    feitos = 0

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(_worker, p, origem, forcar): p for p in pdfs}
        try:
            for fut in as_completed(futuros):
                r = fut.result()
                feitos += 1
                st = r.get("status")
                if st == "processado":
                    ok += 1
                    chunks_total += r.get("chunks", 0)
                    atos_total += r.get("atos", 0)
                    print(f"  [{feitos}/{total}] {r['nome']} — OK: "
                          f"{r.get('chunks')} chunks, {r.get('atos')} atos "
                          f"({r.get('dt', 0):.0f}s)", flush=True)
                elif st == "ja_processado":
                    pulados += 1
                    print(f"  [{feitos}/{total}] {r['nome']} — pulado (ja na base)",
                          flush=True)
                else:
                    erros += 1
                    print(f"  [{feitos}/{total}] {r['nome']} — {st}: "
                          f"{r.get('erro', '')}", flush=True)
        except KeyboardInterrupt:
            print("\nInterrompido — encerrando workers. "
                  "Reexecute para retomar (resumivel).", flush=True)
            pool.shutdown(wait=False, cancel_futures=True)
            raise

    dt = time.time() - t0
    print(f"\n{'='*60}", flush=True)
    print(f"  INGESTAO CONCLUIDA em {dt:.0f}s", flush=True)
    print(f"  {ok} OK, {pulados} pulados, {erros} com erro | "
          f"{chunks_total} chunks, {atos_total} atos", flush=True)
    print(f"{'='*60}\n", flush=True)
    return {"ok": ok, "erros": erros, "pulados": pulados,
            "chunks": chunks_total, "atos": atos_total}


def main():
    pasta = None
    forcar = False
    for arg in sys.argv[1:]:
        if arg == "--forcar":
            forcar = True
        elif not arg.startswith("--"):
            pasta = arg
    ingerir_pasta(pasta=pasta, forcar=forcar)


if __name__ == "__main__":
    main()
