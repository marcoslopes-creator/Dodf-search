"""
processar_pdf.py — Processamento de PDFs (autoEmbed + GridFS)
==============================================================
Melhorias desta versao:
  - Limpeza AGRESSIVA: remove ".....", "_____", "------", linhas pontilhadas
  - Normalizacao de espacos (incluindo nbsp), quebras, paragrafos
  - Overlap GARANTIDO entre chunks via splitter padrao + verificacao
  - Embeddings gerados pelo Atlas (Automated Embedding) a partir de 'texto':
    a aplicacao NAO chama a API da Voyage na ingestao
  - Metadados de edicao (data, numero_edicao, tipo_edicao) extraidos do nome
    do arquivo para pre-filtros do $vectorSearch
  - Logs com flush em todas as etapas

Uso:
  python processar_pdf.py arquivo.pdf
  python processar_pdf.py --reprocessar        (limpa o banco)
  python processar_pdf.py --reprocessar-base   (reprocessa in-place)
  python processar_pdf.py --migrar
  python processar_pdf.py --migrar-metadados   (chunks existentes: metadados
                                                 de edicao + remove 'embedding')
  python processar_pdf.py --testar-limpeza arquivo.pdf
"""

import os
import re
import sys
import time
import hashlib
from datetime import datetime

import fitz
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import get_db, get_gridfs, get_collection, CFG


# =====================================================================
# REGEX COMPILADOS UMA UNICA VEZ
# =====================================================================

# Lixo (linhas inteiras a descartar)
_RE_PAGINACAO = re.compile(r'^P[áa]gina\s+\d+\s+de\s+\d+', re.IGNORECASE)
_RE_EMITIDO = re.compile(r'^Emitido\s+em:', re.IGNORECASE)
_RE_SO_NUMEROS = re.compile(r'^[\d\.\-\s/,]+$')
_RE_COD_ORCAMENTARIO = re.compile(r'^\d{2}\.\d{3}\.\d{4}\.\d{4}\.\d{4}')
_RE_REF = re.compile(r'^REF\.?\s*:?\s*\d+', re.IGNORECASE)
_RE_NATUREZA = re.compile(r'^[3-4][3-4]\d{4}$')
_RE_FONTE_RECURSO = re.compile(r'^\d{4}\s*-\s*\d{4}$')
_RE_VALOR = re.compile(r'^\d{1,3}(\.\d{3})*$')

# Linhas de "preenchimento" — pontos, traços, underscores, etc.
_RE_LINHA_PONTOS = re.compile(r'^[\s\.]{3,}$')
_RE_LINHA_TRACOS = re.compile(r'^[\s\-_=\*]{3,}$')
_RE_SEPARADOR = re.compile(r'^[\-_=\*\.\s]+$')

# Substituicoes inline (dentro do texto)
_RE_PONTOS_REPETIDOS = re.compile(r'\.{4,}')   # 4+ pontos: "....." ou "...."
_RE_TRACOS_REPETIDOS = re.compile(r'-{3,}')    # 3+ tracos: "---"
_RE_UNDERSCORE_REP = re.compile(r'_{3,}')      # 3+ underscores: "___"
_RE_PONTOS_ESPACADOS = re.compile(r'(?:\.\s){3,}\.?')  # ". . . . ." com espacos
_RE_PONTOS_DEPOIS_TEXTO = re.compile(r'(\w)\s*\.{3,}\s*(\w|$)')  # "texto....texto"

# Espacos e quebras
_RE_NBSP = re.compile(r'[\u00a0\u2007\u202f\xa0]')   # nbsp variants
# Invisiveis: zero-width, soft-hyphen, BOM (removidos por completo)
_RE_INVISIVEIS = re.compile(r'[\u200b\u200c\u200d\u00ad\ufeff\u2028\u2029]')
_RE_ESPACOS_HORIZONTAIS = re.compile(r'[ \t\f\v]+')   # multiplos spaces/tabs
_RE_QUEBRAS_MULTIPLAS = re.compile(r'\n{3,}')         # 3+ quebras viram 2
_RE_PARAGRAFO = re.compile(
    r'(?<=[a-zA-ZáéíóúãõâêôçÁÉÍÓÚÃÕÂÊÔÇ,;])\n(?=[a-záéíóúãõâêôç])'
)
_RE_HIFEN_QUEBRA = re.compile(r'(\w+)-\n(\w+)')  # "pala-\nvra" -> "palavra"
_RE_ESPACOS_ANTES_PONT = re.compile(r'\s+([,;:.!?)])')
_RE_ESPACOS_DEPOIS_ABRE = re.compile(r'([(\[])\s+')

# Caracteres especiais comuns em PDF (bullets, etc)
_RE_BULLETS = re.compile(r'[•·∙‣⁃◦●○◆◇■□▪▫]')


# =====================================================================
# DETECCAO DE LIXO
# =====================================================================

def _eh_linha_lixo(linha: str) -> bool:
    """Detecta se a linha inteira deve ser descartada."""
    s = linha.strip()
    if not s or len(s) < 4:
        return True
    if (_RE_PAGINACAO.match(s) or _RE_EMITIDO.match(s) or
            _RE_SO_NUMEROS.match(s) or _RE_COD_ORCAMENTARIO.match(s) or
            _RE_REF.match(s) or _RE_NATUREZA.match(s) or
            _RE_FONTE_RECURSO.match(s) or _RE_VALOR.match(s) or
            _RE_LINHA_PONTOS.match(s) or _RE_LINHA_TRACOS.match(s) or
            _RE_SEPARADOR.match(s)):
        return True
    # Linha com 70%+ digitos
    if len(s) > 3:
        digitos = sum(1 for c in s if c.isdigit())
        if digitos / len(s) > 0.7:
            return True
    # Linha com 50%+ pontuacao/simbolos (provavel ruido)
    if len(s) > 5:
        nao_alfa = sum(1 for c in s if not (c.isalnum() or c.isspace()))
        if nao_alfa / len(s) > 0.5:
            return True
    return False


# =====================================================================
# LIMPEZA DE TEXTO — pipeline em multiplas etapas
# =====================================================================

def _limpar_texto(texto: str) -> str:
    """Pipeline de limpeza — gera texto pronto para chunkificar."""

    # 1. Remove caracteres invisiveis e normaliza espacos
    texto = _RE_INVISIVEIS.sub('', texto)
    texto = _RE_NBSP.sub(' ', texto)
    texto = _RE_BULLETS.sub(' ', texto)

    # 2. Junta palavras quebradas por hifenizacao no fim de linha
    texto = _RE_HIFEN_QUEBRA.sub(r'\1\2', texto)

    # 3. Remove sequencias de pontos/tracos/underscores no MEIO do texto
    #    "Item....valor" -> "Item valor"
    texto = _RE_PONTOS_DEPOIS_TEXTO.sub(r'\1 \2', texto)
    texto = _RE_PONTOS_ESPACADOS.sub(' ', texto)
    texto = _RE_PONTOS_REPETIDOS.sub(' ', texto)
    texto = _RE_TRACOS_REPETIDOS.sub(' ', texto)
    texto = _RE_UNDERSCORE_REP.sub(' ', texto)

    # 4. Normaliza espacos horizontais
    texto = _RE_ESPACOS_HORIZONTAIS.sub(' ', texto)

    # 5. Filtra linhas lixo
    linhas_limpas = []
    branco_anterior = False
    for linha in texto.split('\n'):
        if _eh_linha_lixo(linha):
            if not branco_anterior and linhas_limpas:
                linhas_limpas.append("")
                branco_anterior = True
            continue
        linhas_limpas.append(linha.strip())
        branco_anterior = False
    texto = '\n'.join(linhas_limpas)

    # 6. Junta paragrafos quebrados (texto que continua na proxima linha)
    texto = _RE_PARAGRAFO.sub(' ', texto)

    # 7. Reduz quebras consecutivas
    texto = _RE_QUEBRAS_MULTIPLAS.sub('\n\n', texto)

    # 8. Pontuacao
    texto = _RE_ESPACOS_ANTES_PONT.sub(r'\1', texto)
    texto = _RE_ESPACOS_DEPOIS_ABRE.sub(r'\1', texto)

    # 9. Final: remove espacos duplicados restantes
    texto = re.sub(r' {2,}', ' ', texto)
    texto = re.sub(r'\n +', '\n', texto)
    texto = re.sub(r' +\n', '\n', texto)

    return texto.strip()


def _calcular_qualidade(texto: str) -> dict:
    if not texto or len(texto) < 20:
        return {"palavras": 0, "ratio_alfa": 0, "linhas_uteis": 0, "aprovado": False}

    palavras = len(texto.split())
    total = len(texto)
    alfa = sum(1 for c in texto if c.isalpha())
    ratio_alfa = alfa / total if total > 0 else 0

    linhas = texto.split('\n')
    linhas_uteis = sum(1 for l in linhas if len(l.strip()) > 20 and
                       sum(1 for c in l if c.isalpha()) > len(l.strip()) * 0.3)

    aprovado = (palavras >= 10 and ratio_alfa >= 0.3 and
                (linhas_uteis >= 2 or palavras >= 50))
    return {"palavras": palavras, "ratio_alfa": round(ratio_alfa, 2),
            "linhas_uteis": linhas_uteis, "aprovado": aprovado}


def _limpar_chunk_final(texto: str) -> str:
    """Limpeza final do chunk antes de salvar — remove pontos residuais."""
    # Remove pontos/tracos residuais
    texto = _RE_PONTOS_REPETIDOS.sub(' ', texto)
    texto = _RE_PONTOS_ESPACADOS.sub(' ', texto)
    texto = _RE_TRACOS_REPETIDOS.sub(' ', texto)
    texto = _RE_UNDERSCORE_REP.sub(' ', texto)

    # Remove linhas lixo nas bordas
    linhas = texto.split('\n')
    while linhas and _eh_linha_lixo(linhas[0]):
        linhas.pop(0)
    while linhas and _eh_linha_lixo(linhas[-1]):
        linhas.pop()
    texto = '\n'.join(linhas).strip()

    # Normaliza espacos
    texto = re.sub(r' {2,}', ' ', texto)
    texto = _RE_QUEBRAS_MULTIPLAS.sub('\n\n', texto)
    return texto


# Separadores juridicos (do mais especifico ao mais generico)
SEPARADORES_JURIDICOS = [
    "\n\n",
    "\nArt.", "\nEDITAL", "\nPORTARIA", "\nDECRETO",
    "\nRESOLUCAO", "\nDESPACHO",
    "\n", ". ", "; ", " ",
]


# =====================================================================
# UTILIDADES
# =====================================================================

def _hash_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _ja_processado(hash_md5: str) -> bool:
    return get_db()["pdfs"].find_one(
        {"hash_md5": hash_md5, "status": "processado"}) is not None


def _salvar_no_gridfs(nome: str, data: bytes, hash_md5: str):
    fs = get_gridfs()
    existente = fs.find_one({"filename": nome, "md5_hash": hash_md5})
    if existente:
        return existente._id
    return fs.put(data, filename=nome, md5_hash=hash_md5,
                  upload_date=datetime.now())


# Nome padrao do DODF: "DODF 012 17-01-2025 EDICAO EXTRA A.pdf"
_RE_NOME_DODF = re.compile(
    r'DODF\s+(?P<num>\d{1,4})\s+(?P<d>\d{2})-(?P<m>\d{2})-(?P<a>\d{4})'
    r'(?:\s+(?P<tipo>[^.]+?))?\s*\.pdf$', re.IGNORECASE)


def _metadados_edicao(nome: str) -> dict:
    """Extrai data/numero/tipo da edicao a partir do nome do arquivo.

    Retorna dict vazio se o nome nao segue o padrao do DODF (os chunks
    continuam pesquisaveis; apenas nao entram nos pre-filtros de edicao).
    """
    m = _RE_NOME_DODF.search(nome.strip())
    if not m:
        return {}
    try:
        data = datetime(int(m.group("a")), int(m.group("m")), int(m.group("d")))
    except ValueError:
        return {}
    tipo = (m.group("tipo") or "INTEGRA").strip().upper()
    tipo = re.sub(r'\s+', ' ', tipo)
    return {"data": data, "numero_edicao": int(m.group("num")),
            "tipo_edicao": tipo, "ano": data.year}


def _registrar_pdf(nome, hash_md5, gridfs_id, tamanho, total_paginas,
                   total_chunks, origem):
    col = get_db()["pdfs"]
    campos = {
        "nome_arquivo": nome, "hash_md5": hash_md5,
        "gridfs_id": gridfs_id, "tamanho_bytes": tamanho,
        "total_paginas": total_paginas, "total_chunks": total_chunks,
        "status": "processado", "enviado_por": origem,
        "embedding_modelo": CFG.VOYAGE_EMBEDDING_MODEL,
        "embedding_dimensao": CFG.VOYAGE_EMBEDDING_DIMENSION,
        "embedding_origem": "atlas_auto_embed",
        "data_upload": datetime.now(),
        "data_processamento": datetime.now(),
        "erro": None
    }
    campos.update(_metadados_edicao(nome))
    col.update_one({"hash_md5": hash_md5}, {"$set": campos}, upsert=True)
    return col.find_one({"hash_md5": hash_md5})["_id"]


# =====================================================================
# EXTRACAO COM PROGRESSO POR PAGINA
# =====================================================================

def _ocr_fallback_pagina(page) -> str:
    """Renderiza a pagina como imagem e aplica OCR (provedor configurado)."""
    try:
        from ocr import ocr_imagem_png
        pix = page.get_pixmap(dpi=CFG.OCR_DPI)
        texto = ocr_imagem_png(pix.tobytes("png"))
        return _limpar_texto(texto) if texto else ""
    except Exception as e:
        print(f"          OCR pagina falhou: {str(e)[:100]}", flush=True)
        return ""


def _extrair_texto(pdf_bytes: bytes) -> tuple[list, int]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = len(doc)
    paginas = []
    descartadas = 0
    ocr_usadas = 0

    print(f"        Extraindo texto de {total} paginas...", flush=True)
    t0 = time.time()

    for num in range(total):
        t_pag = time.time()
        try:
            texto_bruto = doc[num].get_text("text", sort=True)
            texto_limpo = _limpar_texto(texto_bruto)
        except Exception as e:
            print(f"          Pagina {num+1}: erro ({e}) — pulando", flush=True)
            descartadas += 1
            continue

        qualidade = (_calcular_qualidade(texto_limpo) if texto_limpo
                     else {"aprovado": False})

        # Fallback de OCR: so quando a extracao nativa falha/e fraca
        precisa_ocr = (not qualidade.get("aprovado")
                       or len(texto_limpo) < CFG.OCR_MIN_CHARS)
        if (precisa_ocr and CFG.OCR_ENABLED
                and ocr_usadas < CFG.OCR_MAX_PAGES_POR_PDF):
            texto_ocr = _ocr_fallback_pagina(doc[num])
            if texto_ocr:
                ocr_usadas += 1
                q_ocr = _calcular_qualidade(texto_ocr)
                if q_ocr.get("aprovado") and (not qualidade.get("aprovado")
                                              or len(texto_ocr) > len(texto_limpo)):
                    texto_limpo, qualidade = texto_ocr, q_ocr

        if texto_limpo and qualidade.get("aprovado"):
            paginas.append({"pagina": num + 1, "texto": texto_limpo,
                            "qualidade": qualidade})
        else:
            descartadas += 1

        dt_pag = time.time() - t_pag
        if (num + 1) % 10 == 0 or dt_pag > 2:
            print(f"          [{num+1}/{total}] {len(paginas)} uteis "
                  f"({dt_pag*1000:.0f}ms)", flush=True)

    doc.close()
    dt = time.time() - t0
    extra = f", {ocr_usadas} via OCR" if ocr_usadas else ""
    print(f"        Extracao OK: {dt:.1f}s — {len(paginas)} uteis, "
          f"{descartadas} descartadas{extra}", flush=True)
    return paginas, total


# =====================================================================
# CRIACAO DE CHUNKS COM OVERLAP GARANTIDO
# =====================================================================

def _criar_chunks(paginas: list, nome: str, total_paginas: int) -> list:
    """Divide texto em chunks com OVERLAP garantido entre eles."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CFG.CHUNK_SIZE,
        chunk_overlap=CFG.CHUNK_OVERLAP,
        length_function=len,
        separators=SEPARADORES_JURIDICOS,
        keep_separator=False,
    )

    print(f"        Criando chunks de {len(paginas)} paginas "
          f"(size={CFG.CHUNK_SIZE}, overlap={CFG.CHUNK_OVERLAP})...", flush=True)
    t0 = time.time()

    # Concatena TODO o texto do PDF preservando paginas
    texto_completo = ""
    mapa_paginas = []  # lista de (pos_inicio, pos_fim, num_pagina)

    for info in paginas:
        ini = len(texto_completo)
        texto_completo += info["texto"] + "\n\n"
        fim = len(texto_completo)
        mapa_paginas.append((ini, fim, info["pagina"]))

    # Chunks com overlap (vem do splitter)
    pedacos = splitter.split_text(texto_completo)

    chunks = []
    descartados = 0
    pos_busca = 0  # posicao corrente no texto_completo
    edicao = _metadados_edicao(nome)

    for numero, pedaco in enumerate(pedacos, 1):
        pedaco_limpo = _limpar_chunk_final(pedaco)
        qualidade = _calcular_qualidade(pedaco_limpo)

        if not (qualidade["aprovado"] and len(pedaco_limpo) > 50):
            descartados += 1
            continue

        # Localiza o pedaco no texto completo para identificar paginas
        idx = texto_completo.find(pedaco[:100], pos_busca)
        if idx == -1:
            idx = texto_completo.find(pedaco[:50], pos_busca)
        if idx == -1:
            idx = pos_busca

        pos_inicio = idx
        pos_fim = idx + len(pedaco)
        # Avanca a busca, mas mantem zona de overlap
        pos_busca = max(pos_inicio, pos_fim - CFG.CHUNK_OVERLAP)

        # Identifica em que pagina(s) o chunk esta
        pags_chunk = []
        for ini, fim, pag in mapa_paginas:
            if pos_inicio < fim and pos_fim > ini:
                pags_chunk.append(pag)
        if not pags_chunk:
            pags_chunk = [1]

        # Texto do overlap com o chunk anterior (para validacao/debug)
        overlap_anterior = ""
        if chunks:
            anterior = chunks[-1]["texto"]
            tail = anterior[-CFG.CHUNK_OVERLAP:] if len(anterior) > CFG.CHUNK_OVERLAP else anterior
            # Procura ponto de overlap real
            for tamanho in range(min(200, len(tail), len(pedaco_limpo)), 30, -10):
                if tail[-tamanho:] in pedaco_limpo[:300]:
                    overlap_anterior = tail[-tamanho:]
                    break

        metadados = {
            "arquivo": nome,
            "pagina": pags_chunk[0],
            "paginas_grupo": pags_chunk,
            "chunk_numero": len(chunks) + 1,
            "total_paginas": total_paginas,
            "tamanho_chars": len(pedaco_limpo),
            "palavras": qualidade["palavras"],
            "ratio_alfa": qualidade["ratio_alfa"],
            "tem_overlap_anterior": bool(overlap_anterior),
            "overlap_chars": len(overlap_anterior),
            "processado_em": datetime.now()
        }
        metadados.update(edicao)
        chunks.append({"texto": pedaco_limpo, "metadados": metadados})

    dt = time.time() - t0
    com_overlap = sum(1 for c in chunks if c["metadados"]["tem_overlap_anterior"])
    print(f"        Chunks: {len(chunks)} criados "
          f"({descartados} descartados, {com_overlap} com overlap) em {dt:.1f}s",
          flush=True)
    return chunks


# =====================================================================
# PERSISTENCIA DOS CHUNKS (embeddings gerados pelo Atlas autoEmbed)
# =====================================================================

def _salvar_chunks(chunks: list, hash_md5: str, pdf_id=None, callback=None):
    """Grava os chunks em lotes. O vetor e gerado pelo Atlas ao indexar
    o campo 'texto' (indice autoEmbed) — nenhuma chamada a API aqui."""
    col = get_collection()
    LOTE = 500
    total = len(chunks)
    total_lotes = (total + LOTE - 1) // LOTE

    print(f"        Gravando {total} chunks em {total_lotes} lote(s) "
          f"(embedding: Atlas autoEmbed/{CFG.VOYAGE_EMBEDDING_MODEL})",
          flush=True)
    t0 = time.time()

    for i in range(0, total, LOTE):
        lote = chunks[i:i + LOTE]
        docs = []
        for chunk in lote:
            doc = {
                "texto": chunk["texto"],
                "metadados": chunk["metadados"],
                "hash_arquivo": hash_md5,
            }
            if pdf_id:
                doc["pdf_id"] = pdf_id
            docs.append(doc)
        col.insert_many(docs, ordered=False)

        feitos = min(i + LOTE, total)
        pct = int(feitos / total * 100)
        if callback:
            callback(feitos, total, pct)
        else:
            print(f"        [{i // LOTE + 1}/{total_lotes}] {feitos}/{total} "
                  f"({pct}%)", flush=True)

    print(f"        ✅ Chunks gravados em {time.time() - t0:.1f}s "
          f"(vetores serao gerados pelo indice)", flush=True)


# =====================================================================
# EXTRACAO ESTRUTURADA DE ATOS (Fase 1 — hibrido regex + LLM)
# =====================================================================

def _extrair_e_salvar_atos(chunks: list, hash_md5: str) -> int:
    """Extrai atos dos chunks e grava na colecao atos (idempotente)."""
    if not CFG.ATOS_EXTRACTION_ENABLED:
        return 0
    from extrator_atos import extrair_atos

    col = get_db()[CFG.ATOS_COLLECTION]
    col.delete_many({"hash_arquivo": hash_md5})  # reprocesso limpo

    vistos, docs = set(), []
    for c in chunks:
        md = c["metadados"]
        for ato in extrair_atos(c["texto"], md["arquivo"],
                                md["pagina"], hash_md5):
            chave = (ato["nome_normalizado"], ato["tipo_ato"], ato["pagina"])
            if chave in vistos:
                continue
            vistos.add(chave)
            docs.append(ato)

    if docs:
        col.insert_many(docs)
    print(f"        Atos extraidos: {len(docs)}", flush=True)
    return len(docs)


# =====================================================================
# FUNCOES PUBLICAS
# =====================================================================

def processar_pdf_bytes(nome: str, data: bytes, origem: str = "upload_web",
                         callback=None) -> dict:
    hash_md5 = _hash_bytes(data)

    if _ja_processado(hash_md5):
        return {"status": "ja_processado", "nome": nome, "hash": hash_md5}

    col_pdfs = get_db()["pdfs"]
    col_pdfs.update_one(
        {"hash_md5": hash_md5},
        {"$set": {"nome_arquivo": nome, "hash_md5": hash_md5,
                  "status": "processando", "enviado_por": origem,
                  "data_upload": datetime.now()}},
        upsert=True
    )

    try:
        print(f"        Salvando no GridFS...", end=" ", flush=True)
        gridfs_id = _salvar_no_gridfs(nome, data, hash_md5)
        print(f"OK ({len(data)/1024/1024:.1f} MB)", flush=True)

        paginas, total_pags = _extrair_texto(data)
        if not paginas:
            col_pdfs.update_one({"hash_md5": hash_md5},
                                 {"$set": {"status": "erro",
                                           "erro": "Sem texto extraivel"}})
            return {"status": "erro", "nome": nome,
                    "erro": "Sem texto extraivel (PDF escaneado?)"}

        chunks = _criar_chunks(paginas, nome, total_pags)
        if not chunks:
            col_pdfs.update_one({"hash_md5": hash_md5},
                                 {"$set": {"status": "erro",
                                           "erro": "Chunks descartados"}})
            return {"status": "erro", "nome": nome,
                    "erro": "Conteudo insuficiente apos limpeza"}

        pdf_id = col_pdfs.find_one({"hash_md5": hash_md5})["_id"]
        _salvar_chunks(chunks, hash_md5, pdf_id=pdf_id, callback=callback)
        n_atos = _extrair_e_salvar_atos(chunks, hash_md5)
        _registrar_pdf(nome, hash_md5, gridfs_id, len(data),
                        total_pags, len(chunks), origem)

        return {"status": "processado", "nome": nome, "paginas": total_pags,
                "chunks": len(chunks), "atos": n_atos, "hash": hash_md5}

    except Exception as e:
        col_pdfs.update_one({"hash_md5": hash_md5},
                             {"$set": {"status": "erro", "erro": str(e)}})
        return {"status": "erro", "nome": nome, "erro": str(e)}


def processar_pdf(caminho: str, origem: str = "local"):
    nome = os.path.basename(caminho)
    tam_mb = os.path.getsize(caminho) / 1024 / 1024
    print(f"\n{'='*60}", flush=True)
    print(f"  PROCESSANDO: {nome} ({tam_mb:.1f} MB)", flush=True)
    print(f"  Embedding: Atlas autoEmbed / {CFG.VOYAGE_EMBEDDING_MODEL} "
          f"({CFG.VOYAGE_EMBEDDING_DIMENSION}d)", flush=True)
    print(f"{'='*60}", flush=True)

    t0 = time.time()
    with open(caminho, "rb") as f:
        data = f.read()
    resultado = processar_pdf_bytes(nome, data, origem=origem)
    dt = time.time() - t0

    if resultado["status"] == "ja_processado":
        print(f"  ⏭️  Ja processado", flush=True)
    elif resultado["status"] == "erro":
        print(f"  ❌ ERRO: {resultado['erro']}", flush=True)
    else:
        print(f"  ✅ {dt:.0f}s: {resultado['paginas']} pgs, "
              f"{resultado['chunks']} chunks", flush=True)
    print(f"{'='*60}\n", flush=True)
    return resultado


def migrar_pdfs_para_gridfs():
    import glob
    pasta = CFG.PDF_FOLDER
    if not pasta or not os.path.isdir(pasta):
        print(f"PDF_FOLDER nao existe: {pasta}")
        return
    pdfs = sorted(glob.glob(os.path.join(pasta, "*.pdf")))
    print(f"Encontrados {len(pdfs)} PDFs em {pasta}")
    for i, caminho in enumerate(pdfs, 1):
        nome = os.path.basename(caminho)
        with open(caminho, "rb") as f:
            data = f.read()
        hash_md5 = _hash_bytes(data)
        gridfs_id = _salvar_no_gridfs(nome, data, hash_md5)
        col = get_db()["pdfs"]
        if not col.find_one({"hash_md5": hash_md5}):
            n_chunks = get_collection().count_documents(
                {"hash_arquivo": hash_md5})
            doc = fitz.open(caminho)
            total_pags = len(doc)
            doc.close()
            col.insert_one({
                "nome_arquivo": nome, "hash_md5": hash_md5,
                "gridfs_id": gridfs_id, "tamanho_bytes": len(data),
                "total_paginas": total_pags, "total_chunks": n_chunks,
                "status": "processado" if n_chunks > 0 else "pendente",
                "enviado_por": "migracao",
                "data_upload": datetime.now(),
                "data_processamento": datetime.now() if n_chunks > 0 else None,
            })
            status = "migrado" if n_chunks > 0 else "pendente"
        else:
            status = "ja existe"
        print(f"  [{i}/{len(pdfs)}] {nome} — {status}")
    print(f"\nMigracao concluida.")


def reprocessar_base():
    """Reprocessa, in-place, todos os PDFs da pasta que ja estao na base.

    Para cada arquivo: remove os chunks antigos + o registro em 'pdfs'
    (os atos sao limpos pelo proprio _extrair_e_salvar_atos) e reprocessa,
    regenerando chunks/embeddings/atos com a extracao melhorada.
    Idempotente e resumivel: pode rodar de novo com seguranca.
    """
    import glob
    pasta = CFG.PDF_FOLDER
    if not pasta or not os.path.isdir(pasta):
        print(f"PDF_FOLDER nao existe: {pasta}")
        return
    pdfs = sorted(glob.glob(os.path.join(pasta, "*.pdf")))
    total = len(pdfs)
    col_chunks = get_collection()
    col_pdfs = get_db()["pdfs"]

    print(f"\n{'='*60}")
    print(f"  REPROCESSAMENTO IN-PLACE — {total} PDF(s)")
    print(f"  OCR_ENABLED={CFG.OCR_ENABLED} | provider={CFG.OCR_PROVIDER}")
    print(f"{'='*60}\n", flush=True)

    t0 = time.time()
    ok = erros = atos_total = chunks_total = 0
    for i, caminho in enumerate(pdfs, 1):
        nome = os.path.basename(caminho)
        with open(caminho, "rb") as f:
            data = f.read()
        hash_md5 = _hash_bytes(data)
        col_chunks.delete_many({"hash_arquivo": hash_md5})
        col_pdfs.delete_one({"hash_md5": hash_md5})
        try:
            r = processar_pdf_bytes(nome, data, origem="reprocessamento")
            if r.get("status") == "processado":
                ok += 1
                chunks_total += r.get("chunks", 0)
                atos_total += r.get("atos", 0)
                print(f"  [{i}/{total}] {nome} — OK: "
                      f"{r.get('chunks')} chunks, {r.get('atos')} atos",
                      flush=True)
            else:
                erros += 1
                print(f"  [{i}/{total}] {nome} — {r.get('status')}: "
                      f"{r.get('erro','')}", flush=True)
        except Exception as e:
            erros += 1
            print(f"  [{i}/{total}] {nome} — ERRO: {str(e)[:120]}", flush=True)

    dt = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  REPROCESSAMENTO CONCLUIDO em {dt:.0f}s")
    print(f"  {ok} OK, {erros} com erro | "
          f"{chunks_total} chunks, {atos_total} atos")
    print(f"{'='*60}\n", flush=True)


def limpar_banco():
    db = get_db()
    r = get_collection().delete_many({})
    print(f"  Chunks removidos: {r.deleted_count}")
    r = db["pdfs"].delete_many({})
    print(f"  Registros PDFs removidos: {r.deleted_count}")


def migrar_metadados():
    """Adapta chunks ja ingeridos ao modelo autoEmbed, sem reprocessar PDFs.

    Para cada arquivo distinto: grava metadados.data/numero_edicao/tipo_edicao
    (pre-filtros) e remove o array 'embedding' gerado pela aplicacao — o
    indice autoEmbed gera os vetores a partir de 'texto'. Idempotente.
    """
    col = get_collection()
    col_pdfs = get_db()["pdfs"]
    arquivos = col.distinct("metadados.arquivo")
    print(f"\n{'='*60}\n  MIGRACAO DE METADADOS — {len(arquivos)} arquivo(s)"
          f"\n{'='*60}\n", flush=True)

    t0 = time.time()
    atualizados = sem_padrao = 0
    for i, nome in enumerate(sorted(arquivos), 1):
        edicao = _metadados_edicao(nome)
        upd = {"$unset": {"embedding": "", "metadados.embedding_modelo": "",
                          "metadados.embedding_dimensao": ""}}
        if edicao:
            upd["$set"] = {f"metadados.{k}": v for k, v in edicao.items()}
            edicao_pdf = dict(edicao, embedding_origem="atlas_auto_embed")
            col_pdfs.update_one({"nome_arquivo": nome}, {"$set": edicao_pdf})
        else:
            sem_padrao += 1
        r = col.update_many({"metadados.arquivo": nome}, upd)
        atualizados += r.modified_count
        rotulo = (f"{edicao['data']:%d/%m/%Y} ed.{edicao['numero_edicao']} "
                  f"{edicao['tipo_edicao']}" if edicao else "sem padrao DODF")
        print(f"  [{i}/{len(arquivos)}] {nome[:50]:<50} {rotulo} "
              f"({r.modified_count} chunks)", flush=True)

    print(f"\n  Concluido em {time.time() - t0:.0f}s: {atualizados} chunks "
          f"atualizados, {sem_padrao} arquivo(s) fora do padrao.", flush=True)


def testar_limpeza(caminho: str):
    """Testa limpeza E overlap em modo verbose — diagnostico."""
    nome = os.path.basename(caminho)
    print(f"\n{'='*60}\n  TESTE DE LIMPEZA + OVERLAP: {nome}\n{'='*60}")
    with open(caminho, "rb") as f:
        data = f.read()

    # Etapa 1: Limpeza por pagina
    doc = fitz.open(stream=data, filetype="pdf")
    total = len(doc)
    print(f"  Total: {total} paginas\n")
    paginas = []
    for num in range(min(total, 5)):
        bruto = doc[num].get_text("text", sort=True)
        limpo = _limpar_texto(bruto)
        q = _calcular_qualidade(limpo)
        retido = len(limpo) / max(len(bruto), 1) * 100
        print(f"  --- Pagina {num+1} ---")
        print(f"  Bruto: {len(bruto)} chars | Limpo: {len(limpo)} chars ({retido:.0f}%)")
        print(f"  Qualidade: palavras={q['palavras']}, alfa={q['ratio_alfa']}, aprovado={'SIM' if q['aprovado'] else 'NAO'}")

        # Mostra exemplos de "antes/depois" de problemas comuns
        if '...' in bruto:
            occ = bruto.count('...')
            occ_limpo = limpo.count('...')
            print(f"  Pontos '...': {occ} no bruto -> {occ_limpo} no limpo")
        if '\n\n\n' in bruto:
            print(f"  Quebras triplas removidas: {bruto.count(chr(10)*3)}")

        if q["aprovado"]:
            paginas.append({"pagina": num + 1, "texto": limpo, "qualidade": q})
        if limpo:
            preview = limpo[:300].replace('\n', ' ↵ ')
            print(f"  Preview: {preview}...\n")
    doc.close()

    # Etapa 2: Chunks com overlap
    if len(paginas) >= 2:
        print(f"\n{'='*60}\n  TESTE DE OVERLAP\n{'='*60}")
        chunks = _criar_chunks(paginas, nome, total)
        print(f"\n  Chunks gerados: {len(chunks)}")
        for i in range(min(3, len(chunks))):
            c = chunks[i]
            md = c["metadados"]
            print(f"\n  --- Chunk {i+1} ---")
            print(f"  Tamanho: {md['tamanho_chars']} chars")
            print(f"  Tem overlap anterior: {md['tem_overlap_anterior']} "
                  f"({md['overlap_chars']} chars)")
            print(f"  Inicio: {c['texto'][:150]}...")
            print(f"  Fim:    ...{c['texto'][-150:]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso:")
        print("  python processar_pdf.py arquivo.pdf")
        print("  python processar_pdf.py --reprocessar       (limpa o banco)")
        print("  python processar_pdf.py --reprocessar-base  (reprocessa in-place)")
        print("  python processar_pdf.py --migrar")
        print("  python processar_pdf.py --migrar-metadados")
        print("  python processar_pdf.py --testar-limpeza arquivo.pdf")
        sys.exit(1)

    flag = sys.argv[1]
    if flag == "--reprocessar":
        limpar_banco()
        print("Banco limpo. Execute: python monitor_pasta.py")
    elif flag == "--reprocessar-base":
        reprocessar_base()
    elif flag == "--migrar":
        migrar_pdfs_para_gridfs()
    elif flag == "--migrar-metadados":
        migrar_metadados()
    elif flag == "--testar-limpeza":
        if len(sys.argv) < 3:
            print("Uso: python processar_pdf.py --testar-limpeza arquivo.pdf")
            sys.exit(1)
        if not os.path.exists(sys.argv[2]):
            print(f"ERRO: nao encontrado: {sys.argv[2]}")
            sys.exit(1)
        testar_limpeza(sys.argv[2])
    else:
        if not os.path.exists(flag):
            print(f"ERRO: nao encontrado: {flag}")
            sys.exit(1)
        processar_pdf(flag)
