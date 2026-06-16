"""
tools_dodf.py — Ferramentas do Agente + Utilitarios
=====================================================
- 10 ferramentas LangGraph (com tracking de tempo)
- Cache semantico, metricas, feedback, historico, auditoria
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
from config import (get_db, get_collection, get_gridfs,
                     gerar_embedding, rerancar, CFG)


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
# BUSCA PARALELA + RERANKING (pipeline rapido)
# =====================================================================

def _busca_txt_raw(col, q: str, lim: int = 8) -> list:
    pipe = [
        {"$search": {"index": "busca_textual", "compound": {"should": [
            {"text": {"query": q, "path": "texto",
                      "fuzzy": {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50}}},
            {"text": {"query": q, "path": "texto.fonetico"}},
            {"text": {"query": q, "path": "texto.normalizado",
                      "fuzzy": {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50}}},
            {"phrase": {"query": q, "path": "texto"}}
        ]}}},
        {"$project": {"texto": 1, "metadados": 1, "score": {"$meta": "searchScore"}}},
        {"$limit": lim}
    ]
    try:
        return list(col.aggregate(pipe))
    except Exception:
        return []


def _busca_sem_raw(col, vetor: list, lim: int = 8) -> list:
    pipe = [
        {"$vectorSearch": {"index": "busca_vetorial", "path": "embedding",
                            "queryVector": vetor, "numCandidates": 150, "limit": lim}},
        {"$project": {"texto": 1, "metadados": 1, "score": {"$meta": "vectorSearchScore"}}}
    ]
    try:
        return list(col.aggregate(pipe))
    except Exception:
        return []


def busca_rapida_paralela(consulta: str, vetor: list, limite: int = 6) -> list:
    """Textual + semantica em paralelo, depois rerank Voyage 4."""
    col = get_collection()
    # Busca mais resultados para o rerank ter o que escolher
    lim_busca = max(limite * 3, 15)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(_busca_txt_raw, col, consulta, lim_busca)
        f2 = ex.submit(_busca_sem_raw, col, vetor, lim_busca)
        txt, sem = f1.result(), f2.result()
    ms_busca = int((time.time() - t0) * 1000)
    _timings_atual.append({"ferramenta": "busca_paralela_mongodb",
                           "tempo_ms": ms_busca, "sucesso": True})

    for r in txt:
        r["tipo_busca"] = "Textual"
    for r in sem:
        r["tipo_busca"] = "Semantica"

    # Combina deduplicando
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

    # Rerank com Voyage 4
    if CFG.RERANK_ENABLED and len(comb) > limite:
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

def verificar_cache(pergunta: str, vetor: list = None,
                    limiar: float = 0.95) -> Optional[str]:
    try:
        db = get_db()
        if vetor is None:
            vetor = gerar_embedding(pergunta)
        r = list(db["cache_semantico"].aggregate([
            {"$vectorSearch": {"index": "cache_vetorial",
                                "path": "pergunta_embedding",
                                "queryVector": vetor,
                                "numCandidates": 10, "limit": 1}},
            {"$project": {"resposta": 1, "score": {"$meta": "vectorSearchScore"}}}
        ]))
        if r and r[0].get("score", 0) >= limiar:
            return r[0]["resposta"]
    except Exception:
        pass
    return None


def salvar_cache(pergunta, resposta, ferramentas, modelo, vetor=None):
    try:
        db = get_db()
        if vetor is None:
            vetor = gerar_embedding(pergunta)
        db["cache_semantico"].insert_one({
            "pergunta": pergunta, "pergunta_embedding": vetor,
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
    """Remove PDF: chunks + registro pdfs + GridFS."""
    db = get_db()
    pdf = db["pdfs"].find_one({"hash_md5": hash_md5})
    if pdf:
        get_collection().delete_many({"hash_arquivo": hash_md5})
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
    """Busca combinada textual + semantica + reranking. Primeira opcao."""
    vetor = gerar_embedding(consulta)
    return _fmt(busca_rapida_paralela(consulta, vetor, limite), limite)


@tool
@_track_tempo("busca_textual_fuzzy")
def busca_textual_fuzzy(consulta: str, limite: int = 8) -> str:
    """Busca tolerante: stemming + fonetico + normalizado + fuzzy.
    Use para nomes proprios com erro de digitacao."""
    return _fmt(_busca_txt_raw(get_collection(), consulta, limite), limite)


@tool
@_track_tempo("busca_semantica")
def busca_semantica(consulta: str, limite: int = 8) -> str:
    """Busca por significado usando vetores Voyage 4."""
    return _fmt(_busca_sem_raw(get_collection(),
                                gerar_embedding(consulta), limite), limite)


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
    """Busca dentro de um PDF especifico."""
    col = get_collection()
    pipe = [
        {"$search": {"index": "busca_textual", "compound": {
            "must": [{"text": {"query": consulta, "path": "texto",
                                "fuzzy": {"maxEdits": 1, "prefixLength": 1,
                                          "maxExpansions": 50}}}],
            "filter": [{"text": {"query": nome_arquivo,
                                  "path": "metadados.arquivo"}}]
        }}},
        {"$project": {"texto": 1, "metadados": 1, "score": {"$meta": "searchScore"}}},
        {"$limit": 8}
    ]
    try:
        return _fmt(list(col.aggregate(pipe)), 8)
    except Exception as e:
        return f"Erro: {e}"


@tool
@_track_tempo("estatisticas_base")
def estatisticas_base() -> str:
    """Estatisticas da base: chunks, PDFs, lista de arquivos."""
    col = get_collection()
    total = col.count_documents({})
    arqs = col.distinct("metadados.arquivo")
    s = f"ESTATISTICAS:\n- Chunks: {total:,}\n- PDFs: {len(arqs)}\n\nARQUIVOS:\n"
    for a in sorted(arqs):
        s += f"  - {a} ({col.count_documents({'metadados.arquivo': a})} chunks)\n"
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


@tool
@_track_tempo("consultar_atos")
def consultar_atos(nome_pessoa: str = "", tipo_ato: str = "",
                    cargo: str = "", orgao: str = "", ano: str = "",
                    mes: str = "") -> str:
    """Consulta PRECISA com contagem EXATA de pessoas via $search + extracao em memoria.
    USE SEMPRE para contagens e listagens.

    EXEMPLOS:
      'quantos pedros nomeados em 2025' -> consultar_atos(nome_pessoa='pedro', tipo_ato='nomeacao', ano='2025')
      'pedro exonerado medico maio 2025' -> consultar_atos(nome_pessoa='pedro', tipo_ato='exoneracao', cargo='medico', ano='2025', mes='maio')
    """
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
        exp = {"nomeacao": "nomeacao nomear nomeado nomeada designar fica nomeado",
                "exoneracao": "exoneracao exonerar exonerado dispensar a pedido",
                "designacao": "designacao designar designado designada",
                "dispensacao": "dispensar dispensado dispensacao"}
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
        ml = mes.lower().strip()
        t = (f"{ml} {mn[ml]}" if ml in mn else
              (f"{mes.zfill(2)}" if mes.isdigit() else ml))
        must.append({"compound": {"should": [
            {"text": {"query": t, "path": "texto"}},
            {"text": {"query": t, "path": "metadados.arquivo"}}
        ]}})
        crit.append(f"mes='{mes}'")

    if not must:
        return "Informe pelo menos um criterio."

    sq = {"index": "busca_textual", "compound": {"must": must}}
    s = f"CONSULTA PRECISA: {' AND '.join(crit)}\n\n"

    total_t = 0
    try:
        cr = list(col.aggregate([
            {"$searchMeta": {"index": "busca_textual",
                              "count": {"type": "total"},
                              "compound": {"must": must}}}
        ]))
        total_t = cr[0].get("count", {}).get("total", 0) if cr else 0
    except Exception:
        pass
    s += f"Trechos encontrados: {total_t}\n\n"
    if total_t == 0:
        return s + "Nenhum resultado. Tente remover filtros ou usar sinonimos."

    try:
        chunks = list(col.aggregate([
            {"$search": sq},
            {"$project": {"texto": 1, "metadados": 1,
                            "score": {"$meta": "searchScore"}}},
            {"$sort": {"score": -1}}, {"$limit": 200}
        ]))
    except Exception as e:
        return f"Erro: {e}"

    # Extracao de nomes via regex em memoria
    RE_NOMES = [
        re.compile(r'(?:NOMEAR|EXONERAR|DESIGNAR|DISPENSAR)\s*,?\s*(?:a\s+pedido\s*,?\s*)?\s*([A-ZÁÉÍÓÚÃÕÂÊÔÇ][A-ZÁÉÍÓÚÃÕÂÊÔÇ\s]{6,60}?)(?:\s*,|\s+para|\s+do\s+Cargo|\s+da\s+Função|\s+matrícula)'),
        re.compile(r'(?:nomeado|nomeada|exonerado|exonerada)\s*,?\s*([A-ZÁÉÍÓÚÃÕÂÊÔÇ][A-ZÁÉÍÓÚÃÕÂÊÔÇ\s]{6,60}?)(?:\s*,|\s+para|\s+do\s+Cargo)'),
    ]
    RE_LIMPA = re.compile(r'\s+(DE|DA|DO|DOS|DAS|E|PARA|A|O)\s*$')
    RE_CARGO = re.compile(r'(?:Cargo\s+(?:em\s+Comissão|de\s+Natureza\s+Especial)|Função\s+de\s+Confiança)[,\s]+(?:Símbolo\s+)?([^,\n]{5,80})')
    RE_ORGAO = re.compile(r'(?:da|do)\s+((?:Secretaria|Administração Regional|Subsecretaria|Diretoria|Casa Civil|Procuradoria)[^,\n\.]{5,100})')

    pessoas = {}
    for chunk in chunks:
        txt = chunk.get("texto", "")
        arq = chunk.get("metadados", {}).get("arquivo", "?")
        pag = chunk.get("metadados", {}).get("pagina", "?")
        for pat in RE_NOMES:
            for m in pat.finditer(txt):
                nome = RE_LIMPA.sub('', m.group(1).strip()).strip()
                if len(nome) > 6 and " " in nome:
                    if nome_pessoa and nome_pessoa.lower() not in nome.lower():
                        continue
                    chave = nome.lower()
                    if chave not in pessoas:
                        pos = txt.upper().find(nome)
                        ctx = txt[max(0, pos):pos + 400]
                        cm = RE_CARGO.search(ctx)
                        om = RE_ORGAO.search(ctx)
                        pessoas[chave] = {
                            "nome": nome.title(),
                            "cargo": cm.group(1).strip() if cm else "",
                            "orgao": om.group(1).strip() if om else "",
                            "fontes": []
                        }
                    fonte = f"{arq}, p.{pag}"
                    if fonte not in pessoas[chave]["fontes"]:
                        pessoas[chave]["fontes"].append(fonte)

    n = len(pessoas)
    s += f"PESSOAS UNICAS: {n}\n(analisados {len(chunks)} de {total_t} trechos)\n\n"
    if n == 0:
        s += "Nomes nao extraidos. Trechos para analise manual:\n\n"
        for i, c in enumerate(chunks[:10], 1):
            md = c.get("metadados", {})
            s += (f"[{i}] {md.get('arquivo', '?')}, p.{md.get('pagina', '?')}\n"
                  f"{c.get('texto', '')[:300].replace(chr(10), ' ')}\n\n")
        return s

    s += "LISTA:\n\n"
    for i, (_, info) in enumerate(sorted(pessoas.items()), 1):
        l = f"{i}. **{info['nome']}**"
        if tipo_ato:
            l += f" — {tipo_ato}"
        if info['cargo']:
            l += f", {info['cargo']}"
        if info['orgao']:
            l += f", {info['orgao']}"
        l += f" (Fonte: {'; '.join(info['fontes'][:3])})"
        s += l + "\n"

    if total_t > len(chunks):
        s += f"\nNOTA: Analisados {len(chunks)} de {total_t} trechos."
    return s


TODAS_FERRAMENTAS = [
    busca_hibrida, busca_textual_fuzzy, busca_semantica,
    contar_e_agrupar, buscar_em_arquivo, estatisticas_base,
    resumo_conversa, refinar_busca, busca_estruturada, consultar_atos,
]
