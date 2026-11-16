"""
tools_dodf.py — Ferramentas do Agente + Utilitarios
=====================================================
- 10 ferramentas LangGraph (com tracking de tempo)
- Busca vetorial com Atlas Automated Embedding: a consulta vai como TEXTO
  no $vectorSearch e o Atlas gera o vetor (voyage-4-lite); os documentos
  foram indexados com voyage-4-large (asymmetric retrieval)
- Pre-filtros do $vectorSearch extraidos da pergunta (data/edicao/tipo)
- Busca hibrida via $rankFusion (RRF no servidor, uma consulta) com
  fallback para fusao no cliente (duas consultas em paralelo)
- Cache semantico (autoEmbed), metricas, feedback, historico, auditoria
- Reranking Voyage 4 nos resultados de busca
- Funcoes de gestao de PDFs (listar, excluir)
"""

import re
import time
import functools
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional
from langchain_core.tools import tool
from config import get_db, get_collection, get_gridfs, rerancar, CFG
from extrator_atos import normalizar, tipo_canonico

_MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
          "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
          "outubro": 10, "novembro": 11, "dezembro": 12}
_MESES_RE = "|".join(sorted(_MESES, key=len, reverse=True))

# Padroes de recorte temporal / de edicao na pergunta
_RE_DATA_NUM = re.compile(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b')
_RE_DATA_EXT = re.compile(
    rf'\b(\d{{1,2}})\s+de\s+({_MESES_RE})\s+de\s+(\d{{4}})\b', re.IGNORECASE)
_RE_MES_ANO = re.compile(
    rf'\b(?:em|de|do|no|durante)\s+({_MESES_RE})\s*(?:de|/)\s*(\d{{4}})\b',
    re.IGNORECASE)
_RE_EDICAO_NUM = re.compile(
    r'\b(?:edi[cç][aã]o|dodf)\s*(?:n[º°o.]?\s*)?(\d{1,4})\b', re.IGNORECASE)
_RE_EXTRA = re.compile(r'\bedi[cç][aã]o\s+extra(?:\s+([a-d]))?\b', re.IGNORECASE)
_RE_SUPLEMENTO = re.compile(r'\bsuplemento\b', re.IGNORECASE)
_TIPOS_EXTRA = ["EDICAO EXTRA A", "EDICAO EXTRA B", "EDICAO EXTRA C", "EDICAO EXTRA D"]


# =====================================================================
# PRE-FILTROS — recorte de edicao extraido da pergunta
# =====================================================================

def extrair_filtros(consulta: str) -> Optional[dict]:
    """Deriva pre-filtros de metadados a partir da pergunta.

    Retorna None quando a pergunta nao tem recorte (comportamento padrao:
    busca em toda a base). Caso contrario, retorna:
      {"mql": {...},        # para $vectorSearch.filter
       "search": [...],     # clausulas para $search.compound.filter
       "descricao": "..."}  # legivel, para logs/UI
    Filtros sao exatos e so usam campos indexados como 'filter'.
    """
    if not CFG.VECTOR_PREFILTER_ENABLED or not consulta:
        return None
    mql, search, desc = {}, [], []

    m = _RE_DATA_NUM.search(consulta) or None
    if m:
        d, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _RE_DATA_EXT.search(consulta)
        if m:
            d, mo, a = int(m.group(1)), _MESES[m.group(2).lower()], int(m.group(3))
    if m:
        try:
            ini = datetime(a, mo, d)
            fim = ini + timedelta(days=1)
            mql["metadados.data"] = {"$gte": ini, "$lt": fim}
            search.append({"range": {"path": "metadados.data", "gte": ini, "lt": fim}})
            desc.append(f"data={ini:%d/%m/%Y}")
        except ValueError:
            pass
    else:
        m = _RE_MES_ANO.search(consulta)
        if m:
            mo, a = _MESES[m.group(1).lower()], int(m.group(2))
            ini = datetime(a, mo, 1)
            fim = datetime(a + (mo == 12), mo % 12 + 1, 1)
            mql["metadados.data"] = {"$gte": ini, "$lt": fim}
            search.append({"range": {"path": "metadados.data", "gte": ini, "lt": fim}})
            desc.append(f"mes={mo:02d}/{a}")

    m = _RE_EDICAO_NUM.search(consulta)
    if m and 0 < int(m.group(1)) <= 400:   # evita "DODF 2025" (ano) como edicao
        n = int(m.group(1))
        mql["metadados.numero_edicao"] = n
        search.append({"equals": {"path": "metadados.numero_edicao", "value": n}})
        desc.append(f"edicao={n}")

    m = _RE_EXTRA.search(consulta)
    if m:
        if m.group(1):
            tipos = [f"EDICAO EXTRA {m.group(1).upper()}"]
        else:
            tipos = _TIPOS_EXTRA
        mql["metadados.tipo_edicao"] = {"$in": tipos}
        search.append({"text": {"path": "metadados.tipo_edicao", "query": tipos}})
        desc.append("tipo=EXTRA" + (f" {m.group(1).upper()}" if m.group(1) else ""))
    elif _RE_SUPLEMENTO.search(consulta):
        mql["metadados.tipo_edicao"] = "SUPLEMENTO"
        search.append({"text": {"path": "metadados.tipo_edicao", "query": "SUPLEMENTO"}})
        desc.append("tipo=SUPLEMENTO")

    if not mql:
        return None
    return {"mql": mql, "search": search, "descricao": ", ".join(desc)}


def _filtro_arquivo(nome_arquivo: str) -> dict:
    return {"mql": {"metadados.arquivo": nome_arquivo},
            "search": [{"text": {"path": "metadados.arquivo", "query": nome_arquivo}}],
            "descricao": f"arquivo={nome_arquivo}"}


# =====================================================================
# TIMING TRACKER — medicao do tempo de cada ferramenta
# =====================================================================

_timings_atual = []


def reset_timings():
    """Reseta o tracker (chamar antes de cada pergunta)."""
    global _timings_atual
    _timings_atual = []


def get_timings() -> list:
    """Retorna lista de timings da pergunta atual."""
    return list(_timings_atual)


def _track_tempo(nome_ferramenta: str):
    """Decorator que mede tempo de execucao de uma ferramenta."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            t0 = time.time()
            try:
                resultado = func(*args, **kwargs)
                ms = int((time.time() - t0) * 1000)
                _timings_atual.append({
                    "ferramenta": nome_ferramenta,
                    "tempo_ms": ms,
                    "sucesso": True
                })
                return resultado
            except Exception as e:
                ms = int((time.time() - t0) * 1000)
                _timings_atual.append({
                    "ferramenta": nome_ferramenta,
                    "tempo_ms": ms,
                    "sucesso": False,
                    "erro": str(e)[:100]
                })
                raise
        return wrapper
    return decorator


def _fmt(resultados: list, max_t: int = 6) -> str:
    """Formata lista de resultados como string para o LLM."""
    if not resultados:
        return "Nenhum resultado encontrado."
    s = f"Encontrados {len(resultados)} trechos:\n\n"
    for i, r in enumerate(resultados[:max_t], 1):
        arq = r.get("metadados", {}).get("arquivo", "?")
        pag = r.get("metadados", {}).get("pagina", "?")
        sc = r.get("score", 0)
        rr = r.get("rerank_score")
        score_str = f"Score: {sc:.4f}"
        if rr is not None:
            score_str += f" | Rerank: {rr:.4f}"
        s += f"[TRECHO {i} | Fonte: {arq}, Pagina {pag} | {score_str}]\n"
        s += f"{r.get('texto', '')[:800]}\n\n"
    return s


# =====================================================================
# BUSCA TEXTUAL DIRETA (UI da pagina de busca)
# =====================================================================

def busca_textual_direta(consulta: str, limite: int = 20) -> list:
    """Atlas Search com highlights — para a pagina de busca textual."""
    col = get_collection()
    pipeline = [
        {"$search": {
            "index": "busca_textual",
            "compound": {"should": [
                {"text": {"query": consulta, "path": "texto",
                          "fuzzy": {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50}}},
                {"text": {"query": consulta, "path": "texto.fonetico"}},
                {"text": {"query": consulta, "path": "texto.normalizado",
                          "fuzzy": {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50}}},
                {"phrase": {"query": consulta, "path": "texto"}}
            ]},
            "highlight": {"path": "texto"}
        }},
        {"$project": {"texto": 1, "metadados": 1,
                       "score": {"$meta": "searchScore"},
                       "destaques": {"$meta": "searchHighlights"}}},
        {"$limit": limite}
    ]
    try:
        resultados = list(col.aggregate(pipeline))
        for r in resultados:
            highlights = r.get("destaques", [])
            trechos = []
            for h in highlights:
                textos_hl = h.get("texts", [])
                texto_completo = ""
                hits_pos = []
                for t in textos_hl:
                    ini = len(texto_completo)
                    texto_completo += t.get("value", "")
                    if t.get("type") == "hit":
                        hits_pos.append((ini, len(texto_completo), t["value"]))

                for pos_ini, pos_fim, hit_val in hits_pos:
                    ci = max(0, pos_ini - 60)
                    cf = min(len(texto_completo), pos_fim + 60)
                    if ci > 0:
                        e = texto_completo.find(" ", ci)
                        if e != -1 and e < pos_ini:
                            ci = e + 1
                    if cf < len(texto_completo):
                        e = texto_completo.rfind(" ", pos_fim, cf)
                        if e != -1:
                            cf = e
                    snip = texto_completo[ci:cf].strip().replace(
                        hit_val, f"**{hit_val}**", 1)
                    pre = "..." if ci > 0 else ""
                    suf = "..." if cf < len(texto_completo) else ""
                    trechos.append(f"{pre}{snip}{suf}")

            unicos = []
            for tr in trechos:
                if not any(tr[:40] == e[:40] for e in unicos):
                    unicos.append(tr)
                if len(unicos) >= 2:
                    break
            r["trechos_destaque"] = unicos
        return resultados
    except Exception as e:
        return [{"erro": str(e)}]


def busca_textual_contagem(consulta: str) -> int:
    """Conta total de trechos que casam com a busca."""
    col = get_collection()
    try:
        sq = {"compound": {"should": [
            {"text": {"query": consulta, "path": "texto",
                      "fuzzy": {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50}}},
            {"text": {"query": consulta, "path": "texto.fonetico"}},
            {"text": {"query": consulta, "path": "texto.normalizado",
                      "fuzzy": {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50}}}
        ]}}
        cr = list(col.aggregate([
            {"$searchMeta": {"index": "busca_textual",
                              "count": {"type": "total"}, **sq}}
        ]))
        return cr[0].get("count", {}).get("total", 0) if cr else 0
    except Exception:
        return 0


# =====================================================================
# BUSCA HIBRIDA ($rankFusion ou paralela no cliente) + RERANKING
# =====================================================================

def _stage_search(q: str, filtros: dict = None) -> dict:
    """Stage $search (indice busca_textual) com pre-filtro opcional."""
    compound = {"should": [
        {"text": {"query": q, "path": "texto",
                  "fuzzy": {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50}}},
        {"text": {"query": q, "path": "texto.fonetico"}},
        {"text": {"query": q, "path": "texto.normalizado",
                  "fuzzy": {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50}}},
        {"phrase": {"query": q, "path": "texto"}}
    ]}
    if filtros and filtros.get("search"):
        compound["filter"] = filtros["search"]
    return {"$search": {"index": "busca_textual", "compound": compound}}


def _stage_vector(consulta: str, lim: int, filtros: dict = None) -> dict:
    """Stage $vectorSearch com Automated Embedding: envia o TEXTO da consulta
    e o Atlas gera o vetor com CFG.VOYAGE_QUERY_MODEL (modelo leve, compativel
    com o voyage-4-large usado nos documentos). 'filtros' restringe o espaco
    de busca antes do HNSW (pre-filter)."""
    # numCandidates configuravel (CFG) p/ tuning de recall x latencia com
    # indice quantizado. Floor relativo ao limite garante candidatos suficientes.
    num_cand = max(CFG.VECTOR_NUM_CANDIDATES, lim * 10)
    stage = {"index": CFG.VECTOR_INDEX_NAME, "path": CFG.VECTOR_FIELD,
             "query": consulta, "model": CFG.VOYAGE_QUERY_MODEL,
             "numCandidates": num_cand, "limit": lim}
    if filtros and filtros.get("mql"):
        stage["filter"] = filtros["mql"]
    return {"$vectorSearch": stage}


def _busca_txt_raw(col, q: str, lim: int = 8, filtros: dict = None) -> list:
    pipe = [
        _stage_search(q, filtros),
        {"$project": {"texto": 1, "metadados": 1, "score": {"$meta": "searchScore"}}},
        {"$limit": lim}
    ]
    try:
        return list(col.aggregate(pipe))
    except Exception:
        return []


def _busca_sem_raw(col, consulta: str, lim: int = 8, filtros: dict = None) -> list:
    pipe = [
        _stage_vector(consulta, lim, filtros),
        {"$project": {"texto": 1, "metadados": 1, "score": {"$meta": "vectorSearchScore"}}}
    ]
    try:
        return list(col.aggregate(pipe))
    except Exception:
        return []


_ROTULO_RAMO = {"textual": "Textual", "semantica": "Semantica"}


def _busca_fusao_raw(col, consulta: str, lim: int, filtros: dict = None,
                     detalhes: bool = False) -> list:
    """$rankFusion (MongoDB >= 8.1): $search e $vectorSearch executados e
    fundidos no servidor por Reciprocal Rank Fusion, em uma unica consulta,
    com pesos por ramo (CFG). Cada resultado recebe:
      score        -> score RRF combinado
      tipo_busca   -> 'Hibrida'; com detalhes=True, 'Textual', 'Semantica'
                      ou 'Textual+Semantica' (origem real)
      score_sem    -> score bruto do $vectorSearch (so com detalhes=True)
    'detalhes' pede scoreDetails ao servidor (~+150 ms); use apenas quando
    a origem/score por ramo for necessaria (ex.: RERANK_SKIP_SCORE).
    Levanta excecao se o stage nao for suportado, para o chamador recuar
    para a fusao no cliente."""
    stage = {
        "input": {"pipelines": {
            "textual": [_stage_search(consulta, filtros), {"$limit": lim}],
            "semantica": [_stage_vector(consulta, lim, filtros)]}},
        "combination": {"weights": {
            "textual": CFG.RANKFUSION_PESO_TEXTUAL,
            "semantica": CFG.RANKFUSION_PESO_SEMANTICO}}}
    proj = {"texto": 1, "metadados": 1, "score": {"$meta": "score"}}
    if detalhes:
        stage["scoreDetails"] = True
        proj["_detalhes"] = {"$meta": "scoreDetails"}
    pipe = [
        {"$rankFusion": stage},
        # Uniao dos ramos (ate 2*lim): mesmo pool de candidatos que a fusao
        # no cliente entrega ao reranker.
        {"$limit": lim * 2},
        {"$project": proj}
    ]
    res = list(col.aggregate(pipe))
    for r in res:
        r["tipo_busca"] = "Hibrida"
        if not detalhes:
            continue
        ramos = [d for d in r.pop("_detalhes", {}).get("details", [])
                 if d.get("rank") != "NA"]
        r["tipo_busca"] = "+".join(
            _ROTULO_RAMO[d["inputPipelineName"]] for d in ramos
            if d.get("inputPipelineName") in _ROTULO_RAMO) or "Hibrida"
        for d in ramos:
            if d.get("inputPipelineName") == "semantica":
                r["score_sem"] = d.get("value", 0)
    return res


def _busca_paralela_cliente(col, consulta: str, lim: int, filtros: dict) -> list:
    """Fusao no cliente (fallback): duas consultas em paralelo, intercalacao
    textual/semantica com deduplicacao por _id."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(_busca_txt_raw, col, consulta, lim, filtros)
        f2 = ex.submit(_busca_sem_raw, col, consulta, lim, filtros)
        txt, sem = f1.result(), f2.result()
    for r in txt:
        r["tipo_busca"] = "Textual"
    for r in sem:
        r["tipo_busca"] = "Semantica"
        r["score_sem"] = r.get("score", 0)

    ids, comb = set(), []
    it, iss = 0, 0
    while it < len(txt) or iss < len(sem):
        while it < len(txt):
            rid = str(txt[it]["_id"])
            it += 1
            if rid not in ids:
                ids.add(rid)
                comb.append(txt[it - 1])
                break
        while iss < len(sem):
            rid = str(sem[iss]["_id"])
            iss += 1
            if rid not in ids:
                ids.add(rid)
                comb.append(sem[iss - 1])
                break
    return comb


def busca_rapida_paralela(consulta: str, limite: int = 6,
                          filtros: dict = None) -> list:
    """Busca hibrida textual + semantica, depois rerank Voyage 4.

    Com CFG.RANKFUSION_ENABLED, a fusao e feita pelo Atlas ($rankFusion, uma
    consulta); senao (ou se o stage falhar), duas consultas em paralelo com
    fusao no cliente. 'filtros' (opcional) vem de extrair_filtros()/
    _filtro_arquivo(); quando None, e derivado da propria consulta.
    """
    col = get_collection()
    if filtros is None:
        filtros = extrair_filtros(consulta)
    # Busca mais resultados para o rerank ter o que escolher
    lim_busca = max(limite * 3, 15)

    t0 = time.time()
    comb, modo = None, "rankfusion_mongodb"
    if CFG.RANKFUSION_ENABLED:
        try:
            comb = _busca_fusao_raw(col, consulta, lim_busca, filtros,
                                    detalhes=CFG.RERANK_SKIP_SCORE > 0)
        except Exception:
            comb = None
    if comb is None:
        modo = "busca_paralela_mongodb"
        comb = _busca_paralela_cliente(col, consulta, lim_busca, filtros)
    ms_busca = int((time.time() - t0) * 1000)
    _timings_atual.append({"ferramenta": modo,
                           "tempo_ms": ms_busca, "sucesso": True,
                           "prefiltro": filtros["descricao"] if filtros else None})

    # Rerank condicional: pula a ida extra a API quando ha um vencedor claro
    # (melhor score semantico >= RERANK_SKIP_SCORE), reduzindo latencia.
    melhor_sem = max((r.get("score_sem", 0) for r in comb), default=0)
    pular_rerank = (CFG.RERANK_SKIP_SCORE > 0
                    and melhor_sem >= CFG.RERANK_SKIP_SCORE)

    if CFG.RERANK_ENABLED and len(comb) > limite and not pular_rerank:
        t0 = time.time()
        comb = rerancar(consulta, comb, top_k=limite)
        ms_rerank = int((time.time() - t0) * 1000)
        _timings_atual.append({"ferramenta": "rerank_voyage",
                               "tempo_ms": ms_rerank, "sucesso": True})
    else:
        comb = comb[:limite]

    return comb


# =====================================================================
# CACHE SEMANTICO / METRICAS / FEEDBACK / HISTORICO / AUDITORIA
# =====================================================================

def verificar_cache(pergunta: str, limiar: float = None) -> Optional[str]:
    """Cache semantico via autoEmbed: o Atlas embeda a pergunta (modelo do
    indice, CFG.CACHE_EMBEDDING_MODEL) e compara com perguntas ja respondidas."""
    if limiar is None:
        limiar = CFG.CACHE_SIMILARITY
    try:
        db = get_db()
        r = list(db["cache_semantico"].aggregate([
            {"$vectorSearch": {"index": CFG.CACHE_INDEX_NAME,
                                "path": CFG.CACHE_VECTOR_FIELD,
                                "query": pergunta,
                                "numCandidates": CFG.CACHE_NUM_CANDIDATES,
                                "limit": 1}},
            {"$project": {"resposta": 1, "score": {"$meta": "vectorSearchScore"}}}
        ]))
        if r and r[0].get("score", 0) >= limiar:
            return r[0]["resposta"]
    except Exception:
        pass
    return None


def salvar_cache(pergunta, resposta, ferramentas, modelo):
    """Grava a entrada; o vetor de 'pergunta' e gerado pelo indice autoEmbed."""
    try:
        db = get_db()
        db["cache_semantico"].insert_one({
            "pergunta": pergunta,
            "resposta": resposta, "ferramentas_usadas": ferramentas,
            "modelo": modelo, "criado_em": datetime.now(),
            "ttl": datetime.now() + timedelta(days=7)
        })
    except Exception:
        pass


def registrar_metrica(session_id, pergunta, ferramentas, modelo, tempo_ms,
                      cache_hit, sucesso):
    try:
        get_db()["metricas"].insert_one({
            "session_id": session_id, "pergunta": pergunta,
            "ferramentas_usadas": ferramentas, "modelo_usado": modelo,
            "tempo_total_ms": tempo_ms, "cache_hit": cache_hit,
            "sucesso": sucesso, "timestamp": datetime.now(),
            "ttl": datetime.now() + timedelta(days=30)
        })
    except Exception:
        pass


def salvar_feedback(session_id, pergunta, resposta_resumo, avaliacao,
                     comentario=""):
    try:
        get_db()["feedback"].insert_one({
            "session_id": session_id, "pergunta": pergunta,
            "resposta_resumo": resposta_resumo[:500],
            "avaliacao": avaliacao, "comentario": comentario,
            "timestamp": datetime.now()
        })
    except Exception:
        pass


def carregar_prompt(nome: str) -> str:
    try:
        doc = get_db()["prompt_templates"].find_one({"nome": nome, "ativo": True})
        return doc["prompt"] if doc else ""
    except Exception:
        return ""


def carregar_historico(session_id: str) -> list:
    try:
        doc = get_db()["historico_sessoes"].find_one({"session_id": session_id})
        return doc.get("mensagens", []) if doc else []
    except Exception:
        return []


def salvar_historico(session_id: str, mensagens: list):
    try:
        get_db()["historico_sessoes"].update_one(
            {"session_id": session_id},
            {"$set": {"mensagens": mensagens, "atualizado_em": datetime.now(),
                      "ttl": datetime.now() + timedelta(days=7)},
             "$setOnInsert": {"criado_em": datetime.now()}},
            upsert=True
        )
    except Exception:
        pass


def registrar_auditoria(session_id, pergunta, resposta, modelo, ferramentas,
                        tempo_ms, cache_hit, modo_busca, turno_numero,
                        contexto_anterior, sucesso, erro=None):
    try:
        fontes = re.findall(
            r'(?:Fonte|FONTE|fonte)[:\s]*([^,\n\)]+\.pdf[^,\n\)]*)', resposta)
        if not fontes:
            fontes = re.findall(r'(DODF[^,\n\)]+\.pdf[^,\n\)]*)', resposta)
        get_db()["auditoria"].insert_one({
            "session_id": session_id, "pergunta": pergunta,
            "resposta": resposta, "modelo": modelo,
            "ferramentas_usadas": ferramentas,
            "tempo_resposta_ms": tempo_ms, "cache_hit": cache_hit,
            "modo_busca": modo_busca, "turno_numero": turno_numero,
            "contexto_anterior": contexto_anterior,
            "fontes_citadas": fontes, "sucesso": sucesso,
            "erro": erro, "feedback": None, "timestamp": datetime.now()
        })
    except Exception:
        pass


def atualizar_feedback_auditoria(session_id, pergunta, avaliacao, comentario=""):
    try:
        get_db()["auditoria"].update_one(
            {"session_id": session_id, "pergunta": pergunta},
            {"$set": {"feedback": {"avaliacao": avaliacao,
                                    "comentario": comentario,
                                    "timestamp": datetime.now()}}})
    except Exception:
        pass


def consultar_auditoria(filtros=None, limite=100):
    try:
        return list(get_db()["auditoria"].find(filtros or {}).sort(
            "timestamp", -1).limit(limite))
    except Exception:
        return []


def estatisticas_auditoria():
    try:
        col = get_db()["auditoria"]
        total = col.count_documents({})
        if total == 0:
            return None
        tempos = list(col.aggregate([
            {"$group": {"_id": None, "m": {"$avg": "$tempo_resposta_ms"}}}]))
        ft = list(col.aggregate([
            {"$unwind": "$ferramentas_usadas"},
            {"$group": {"_id": "$ferramentas_usadas.ferramenta",
                         "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}, {"$limit": 5}
        ]))
        mods = list(col.aggregate([
            {"$group": {"_id": "$modelo", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]))
        ch = col.count_documents({"cache_hit": True})
        er = col.count_documents({"sucesso": False})
        return {
            "total_interacoes": total,
            "sessoes_unicas": len(col.distinct("session_id")),
            "feedback_positivo": col.count_documents({"feedback.avaliacao": "positivo"}),
            "feedback_negativo": col.count_documents({"feedback.avaliacao": "negativo"}),
            "taxa_cache": round(ch / total * 100), "com_erro": er,
            "taxa_sucesso": round((total - er) / total * 100),
            "tempo_medio_ms": int(tempos[0]["m"]) if tempos else 0,
            "ferramentas_mais_usadas": ft, "modelos_usados": mods
        }
    except Exception:
        return None


# =====================================================================
# GESTAO DE PDFs (para a pagina Upload/Gestao)
# =====================================================================

def listar_pdfs():
    """Lista todos os PDFs registrados ordenados por data."""
    return list(get_db()["pdfs"].find().sort("data_upload", -1))


def excluir_pdf(hash_md5: str):
    """Remove PDF: chunks + atos + registro pdfs + GridFS."""
    db = get_db()
    pdf = db["pdfs"].find_one({"hash_md5": hash_md5})
    if pdf:
        get_collection().delete_many({"hash_arquivo": hash_md5})
        db[CFG.ATOS_COLLECTION].delete_many({"hash_arquivo": hash_md5})
        gid = pdf.get("gridfs_id")
        if gid:
            try:
                get_gridfs().delete(gid)
            except Exception:
                pass
        db["pdfs"].delete_one({"hash_md5": hash_md5})


# =====================================================================
# FERRAMENTAS DO AGENTE (10)
# =====================================================================

@tool
@_track_tempo("busca_hibrida")
def busca_hibrida(consulta: str, limite: int = 8) -> str:
    """Busca combinada textual + semantica + reranking. Primeira opcao.
    Se a consulta citar data (ex.: 17/01/2025, janeiro de 2025), numero de
    edicao (edicao 12) ou tipo (edicao extra, suplemento), a busca e
    restrita automaticamente a essas edicoes."""
    filtros = extrair_filtros(consulta)
    res = busca_rapida_paralela(consulta, limite, filtros)
    cab = f"[pre-filtro: {filtros['descricao']}]\n" if filtros else ""
    return cab + _fmt(res, limite)


@tool
@_track_tempo("busca_textual_fuzzy")
def busca_textual_fuzzy(consulta: str, limite: int = 8) -> str:
    """Busca tolerante: stemming + fonetico + normalizado + fuzzy.
    Use para nomes proprios com erro de digitacao."""
    return _fmt(_busca_txt_raw(get_collection(), consulta, limite), limite)


@tool
@_track_tempo("busca_semantica")
def busca_semantica(consulta: str, limite: int = 8) -> str:
    """Busca por significado usando vetores Voyage 4 (Atlas autoEmbed)."""
    return _fmt(_busca_sem_raw(get_collection(), consulta, limite,
                                extrair_filtros(consulta)), limite)


@tool
@_track_tempo("contar_e_agrupar")
def contar_e_agrupar(termos_busca: str) -> str:
    """Conta e agrupa ocorrencias de UM termo em toda a base."""
    col = get_collection()
    sq = {"compound": {"should": [
        {"text": {"query": termos_busca, "path": "texto",
                  "fuzzy": {"maxEdits": 1, "prefixLength": 1, "maxExpansions": 50}}},
        {"text": {"query": termos_busca, "path": "texto.fonetico"}},
        {"text": {"query": termos_busca, "path": "texto.normalizado",
                  "fuzzy": {"maxEdits": 1, "prefixLength": 1, "maxExpansions": 50}}}
    ]}}
    s = ""
    try:
        cr = list(col.aggregate([
            {"$searchMeta": {"index": "busca_textual",
                              "count": {"type": "total"}, **sq}}
        ]))
        s += f"TOTAL: {cr[0].get('count', {}).get('total', 0) if cr else 0} trechos\n\n"
    except Exception:
        pass
    try:
        grps = list(col.aggregate([
            {"$search": {"index": "busca_textual", **sq}},
            {"$group": {"_id": "$metadados.arquivo", "count": {"$sum": 1},
                         "paginas": {"$addToSet": "$metadados.pagina"}}},
            {"$sort": {"count": -1}}, {"$limit": 30}
        ]))
        if grps:
            s += f"POR ARQUIVO ({len(grps)} PDFs):\n"
            for g in grps:
                pags = sorted(g["paginas"])[:10]
                s += f"  - {g['_id']}: {g['count']} (pags: {', '.join(str(p) for p in pags)})\n"
    except Exception as e:
        s += f"Erro: {e}\n"
    try:
        am = list(col.aggregate([
            {"$search": {"index": "busca_textual", **sq}},
            {"$project": {"texto": 1, "metadados": 1, "score": {"$meta": "searchScore"}}},
            {"$limit": 10}
        ]))
        if am:
            s += "\nAMOSTRA:\n" + _fmt(am, 10)
    except Exception:
        pass
    return s if s.strip() else "Nenhum resultado."


@tool
@_track_tempo("buscar_em_arquivo")
def buscar_em_arquivo(nome_arquivo: str, consulta: str) -> str:
    """Busca dentro de um PDF especifico (textual + semantica com pre-filtro
    de arquivo + reranking). nome_arquivo deve ser o nome exato do PDF."""
    try:
        res = busca_rapida_paralela(consulta, 8, _filtro_arquivo(nome_arquivo))
        return _fmt(res, 8)
    except Exception as e:
        return f"Erro: {e}"


@tool
@_track_tempo("estatisticas_base")
def estatisticas_base() -> str:
    """Estatisticas da base: chunks, PDFs, lista de arquivos."""
    col = get_collection()
    grupos = list(col.aggregate([
        {"$group": {"_id": "$metadados.arquivo", "chunks": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]))
    total = sum(g["chunks"] for g in grupos)
    s = f"ESTATISTICAS:\n- Chunks: {total:,}\n- PDFs: {len(grupos)}\n\nARQUIVOS:\n"
    for g in grupos:
        s += f"  - {g['_id']} ({g['chunks']} chunks)\n"
    return s


@tool
@_track_tempo("resumo_conversa")
def resumo_conversa(pergunta: str) -> str:
    """Use o contexto da conversa atual para perguntas de acompanhamento."""
    return ("Consulte mensagens anteriores. Extraia nomes, numeros e datas "
            "para formular busca precisa.")


@tool
@_track_tempo("refinar_busca")
def refinar_busca(busca_original: str, resultados_anteriores: str,
                   motivo_refinamento: str) -> str:
    """Sugere estrategias quando uma busca nao trouxe bons resultados."""
    return (f"ESTRATEGIAS para '{busca_original}':\n"
            "1. Para CONTAGEM/LISTA, use 'consultar_atos' com filtros\n"
            "2. Termos mais especificos\n"
            "3. busca_textual_fuzzy para nomes\n"
            "4. busca_semantica para conceitos\n"
            "5. Ampliar limite=15")


@tool
@_track_tempo("busca_estruturada")
def busca_estruturada(nome_pessoa: str = "", tipo_ato: str = "",
                       cargo: str = "", orgao: str = "", ano: str = "",
                       mes: str = "", incluir_amostra: bool = True) -> str:
    """Busca com MULTIPLOS criterios em texto livre.
    Para contagem precisa, prefira consultar_atos."""
    col = get_collection()
    must, crit = [], []

    if nome_pessoa:
        must.append({"compound": {"should": [
            {"text": {"query": nome_pessoa, "path": "texto",
                       "fuzzy": {"maxEdits": 1, "prefixLength": 1}}},
            {"text": {"query": nome_pessoa, "path": "texto.fonetico"}},
            {"text": {"query": nome_pessoa, "path": "texto.normalizado",
                       "fuzzy": {"maxEdits": 1, "prefixLength": 1}}}
        ]}})
        crit.append(f"nome='{nome_pessoa}'")
    if tipo_ato:
        exp = {"nomeacao": "nomeacao nomear nomeado designar fica nomeado",
                "exoneracao": "exoneracao exonerar exonerado dispensar a pedido",
                "designacao": "designacao designar designado",
                "portaria": "portaria", "decreto": "decreto", "edital": "edital"}
        must.append({"text": {"query": exp.get(tipo_ato.lower(), tipo_ato),
                                "path": "texto",
                                "fuzzy": {"maxEdits": 1, "prefixLength": 1}}})
        crit.append(f"tipo='{tipo_ato}'")
    if cargo:
        must.append({"compound": {"should": [
            {"text": {"query": cargo, "path": "texto",
                       "fuzzy": {"maxEdits": 1, "prefixLength": 1}}},
            {"text": {"query": cargo, "path": "texto.normalizado",
                       "fuzzy": {"maxEdits": 1, "prefixLength": 1}}}
        ]}})
        crit.append(f"cargo='{cargo}'")
    if orgao:
        must.append({"compound": {"should": [
            {"text": {"query": orgao, "path": "texto",
                       "fuzzy": {"maxEdits": 1, "prefixLength": 1}}},
            {"text": {"query": orgao, "path": "texto.normalizado",
                       "fuzzy": {"maxEdits": 1, "prefixLength": 1}}}
        ]}})
        crit.append(f"orgao='{orgao}'")
    if ano:
        must.append({"compound": {"should": [
            {"text": {"query": ano, "path": "texto"}},
            {"text": {"query": ano, "path": "metadados.arquivo"}}
        ]}})
        crit.append(f"ano={ano}")
    if mes:
        mn = {"janeiro": "01", "fevereiro": "02", "marco": "03", "março": "03",
               "abril": "04", "maio": "05", "junho": "06", "julho": "07",
               "agosto": "08", "setembro": "09", "outubro": "10",
               "novembro": "11", "dezembro": "12"}
        t = mes.lower() + (" " + mn[mes.lower()] if mes.lower() in mn else "")
        must.append({"compound": {"should": [
            {"text": {"query": t, "path": "texto"}},
            {"text": {"query": t, "path": "metadados.arquivo"}}
        ]}})
        crit.append(f"mes='{mes}'")

    if not must:
        return "Informe pelo menos um criterio."

    sq = {"index": "busca_textual", "compound": {"must": must}}
    s = f"BUSCA ESTRUTURADA: {' AND '.join(crit)}\n\n"
    total = 0
    try:
        cr = list(col.aggregate([
            {"$searchMeta": {"index": "busca_textual",
                              "count": {"type": "total"},
                              "compound": {"must": must}}}
        ]))
        total = cr[0].get("count", {}).get("total", 0) if cr else 0
        s += f"TOTAL: {total} trechos\n\n"
    except Exception:
        pass
    if total == 0:
        return s + "Nenhum resultado."
    try:
        grps = list(col.aggregate([
            {"$search": sq},
            {"$group": {"_id": "$metadados.arquivo", "count": {"$sum": 1},
                         "paginas": {"$addToSet": "$metadados.pagina"}}},
            {"$sort": {"count": -1}}, {"$limit": 30}
        ]))
        if grps:
            s += f"POR ARQUIVO ({len(grps)} PDFs):\n"
            for g in grps:
                s += (f"  - {g['_id']}: {g['count']} "
                      f"(pags: {', '.join(str(p) for p in sorted(g['paginas'])[:10])})\n")
            s += "\n"
    except Exception:
        pass
    if incluir_amostra:
        try:
            am = list(col.aggregate([
                {"$search": sq},
                {"$project": {"texto": 1, "metadados": 1,
                                "score": {"$meta": "searchScore"}}},
                {"$sort": {"score": -1}}, {"$limit": 50}
            ]))
            if am:
                s += f"AMOSTRA ({len(am)} trechos):\n\n"
                for i, r in enumerate(am, 1):
                    arq = r.get("metadados", {}).get("arquivo", "?")
                    pag = r.get("metadados", {}).get("pagina", "?")
                    s += (f"[{i}] {arq}, p.{pag} (score:{r.get('score',0):.1f})\n"
                          f"{r.get('texto','')[:400].replace(chr(10),' ')}\n\n")
        except Exception:
            pass
    s += "\nIdentifique pessoas UNICAS. Cite nomes completos e fontes."
    return s


def _consultar_atos(nome_pessoa: str = "", tipo_ato: str = "", cargo: str = "",
                    orgao: str = "", ano: str = "", mes: str = "") -> str:
    """Nucleo da consulta de atos — contagem EXATA via colecao 'atos'."""
    col = get_db()[CFG.ATOS_COLLECTION]
    filtro, crit = {}, []

    if nome_pessoa:
        # \b garante correspondencia por palavra inteira: 'pedro' casa
        # 'Pedro Silva'/'Joao Pedro' mas nao 'Pedroso'/'Pedrosa'.
        termo = re.escape(normalizar(nome_pessoa))
        filtro["nome_normalizado"] = {"$regex": rf"\b{termo}\b"}
        crit.append(f"nome='{nome_pessoa}'")
    if tipo_ato:
        tc = tipo_canonico(tipo_ato)
        filtro["tipo_ato"] = tc
        crit.append(f"tipo='{tc}'")
    if cargo:
        filtro["cargo"] = {"$regex": re.escape(cargo), "$options": "i"}
        crit.append(f"cargo='{cargo}'")
    if orgao:
        filtro["orgao"] = {"$regex": re.escape(orgao), "$options": "i"}
        crit.append(f"orgao='{orgao}'")
    if ano:
        try:
            filtro["ano"] = int(str(ano).strip())
            crit.append(f"ano={ano}")
        except ValueError:
            pass
    if mes:
        ml = str(mes).lower().strip()
        mv = _MESES.get(ml, int(ml) if ml.isdigit() else None)
        if mv:
            filtro["mes"] = mv
            crit.append(f"mes={mv}")

    s = f"CONSULTA PRECISA (colecao atos): {' AND '.join(crit) or 'sem filtros'}\n\n"

    if col.estimated_document_count() == 0:
        return s + ("Colecao 'atos' vazia. Rode o back-fill: "
                    "python backfill_atos.py")

    total_atos = col.count_documents(filtro)
    if total_atos == 0:
        return s + "Nenhum ato encontrado com esses criterios."

    grupos = list(col.aggregate([
        {"$match": filtro},
        {"$group": {"_id": "$nome_normalizado",
                    "nome": {"$first": "$nome"},
                    "cargo": {"$first": "$cargo"},
                    "orgao": {"$first": "$orgao"},
                    "fontes": {"$addToSet": {"arquivo": "$arquivo",
                                              "pagina": "$pagina"}},
                    "ocorrencias": {"$sum": 1}}},
        {"$sort": {"nome": 1}},
    ]))

    s += f"PESSOAS UNICAS: {len(grupos)}\nTOTAL DE ATOS: {total_atos}\n\nLISTA:\n\n"
    for i, g in enumerate(grupos, 1):
        l = f"{i}. **{g['nome']}**"
        if tipo_ato:
            l += f" — {tipo_canonico(tipo_ato)}"
        if g.get("cargo"):
            l += f", {g['cargo']}"
        if g.get("orgao"):
            l += f", {g['orgao']}"
        fontes = g.get("fontes", [])[:3]
        fs = "; ".join(f"{f.get('arquivo', '?')}, p.{f.get('pagina', '?')}"
                       for f in fontes)
        l += f" (Fonte: {fs})"
        s += l + "\n"
    return s


@tool
@_track_tempo("consultar_atos")
def consultar_atos(nome_pessoa: str = "", tipo_ato: str = "",
                    cargo: str = "", orgao: str = "", ano: str = "",
                    mes: str = "") -> str:
    """Consulta PRECISA com contagem EXATA de pessoas na colecao 'atos'.
    USE SEMPRE para contagens e listagens.

    EXEMPLOS:
      'quantos pedros nomeados em 2025' -> consultar_atos(nome_pessoa='pedro', tipo_ato='nomeacao', ano='2025')
      'pedro exonerado medico maio 2025' -> consultar_atos(nome_pessoa='pedro', tipo_ato='exoneracao', cargo='medico', ano='2025', mes='maio')
    """
    return _consultar_atos(nome_pessoa, tipo_ato, cargo, orgao, ano, mes)


TODAS_FERRAMENTAS = [
    busca_hibrida, busca_textual_fuzzy, busca_semantica,
    contar_e_agrupar, buscar_em_arquivo, estatisticas_base,
    resumo_conversa, refinar_busca, busca_estruturada, consultar_atos,
]
