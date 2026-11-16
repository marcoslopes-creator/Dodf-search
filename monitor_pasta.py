"""
monitor_pasta.py — Monitor de Pasta de PDFs
=============================================
Processa PDFs existentes na pasta + monitora novos arquivos.

Uso: python monitor_pasta.py
"""

import os
import sys
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from config import CFG
from processar_pdf import processar_pdf
from ingestao_paralela import ingerir_pasta


class MonitorPDF(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.lower().endswith(".pdf"):
            nome = os.path.basename(event.src_path)
            print(f"\n>>> Novo PDF detectado: {nome}")
            time.sleep(3)  # Aguarda escrita completa
            try:
                processar_pdf(event.src_path, origem="monitor_pasta")
            except Exception as e:
                print(f"ERRO ao processar {nome}: {e}")


def processar_existentes(pasta: str):
    """Varredura inicial paralela e resumivel (V2 #1)."""
    ingerir_pasta(pasta=pasta, origem="monitor_pasta")


def main():
    pasta = CFG.PDF_FOLDER
    if not pasta or not os.path.isdir(pasta):
        print(f"ERRO: Pasta nao encontrada: {pasta}")
        print(f"Configure PDF_FOLDER no .env")
        sys.exit(1)

    processar_existentes(pasta)

    print(f"\n{'='*60}")
    print(f"  MONITORAMENTO ATIVO")
    print(f"  Pasta: {pasta}")
    print(f"  Aguardando novos PDFs... (Ctrl+C para parar)")
    print(f"{'='*60}\n")

    observer = Observer()
    observer.schedule(MonitorPDF(), pasta, recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nMonitoramento encerrado.")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
