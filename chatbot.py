"""
chatbot.py — Casa Civil DF — Assistente DODF (Voyage 4 Enterprise)
====================================================================
4 paginas: Chat (IA) | Busca Textual | Upload PDFs | Auditoria

Adicional v2:
  - Marcador de tempo por ferramenta (busca MongoDB, rerank, etc.)
"""

import os
import re
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import quote, unquote
import streamlit as st
from datetime import datetime, timedelta
from langchain_core.messages import HumanMessage, AIMessage
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from config import get_db, get_gridfs, gerar_embedding, CFG
from tools_dodf import (
    TODAS_FERRAMENTAS, busca_rapida_paralela,
    busca_textual_direta, busca_textual_contagem,
    verificar_cache, salvar_cache, registrar_metrica,
    salvar_feedback, carregar_prompt,
    carregar_historico, salvar_historico,
    registrar_auditoria, atualizar_feedback_auditoria,
    consultar_auditoria, estatisticas_auditoria,
    listar_pdfs, excluir_pdf,
    reset_timings, get_timings,
    _consultar_atos, _MESES,
)
from processar_pdf import processar_pdf_bytes
from nl2query import interpretar
from ui_theme import aplicar_tema, cabecalho, marca_sidebar


DEFAULT_PROMPT = """Voce e um assistente do DODF. Responda em portugues. Cite fontes."""

PROMPT_RAPIDO = """Voce e o assistente da Casa Civil do DF, especializado no Diario Oficial.
Responda SOMENTE com base nos trechos fornecidos. EXTRAIA dados exatos.
SEMPRE cite fonte: (Fonte: arquivo, Pagina X). NAO invente."""


# =====================================================================
# HTTP SERVER — serve PDFs do GridFS na porta 8502
# =====================================================================

class _GridFSHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        nome = unquote(self.path.lstrip("/").split("#")[0].split("?")[0])
        if not nome:
            self.send_error(404)
            return
        try:
            fs = get_gridfs()
            arq = fs.find_one({"filename": nome})
            if arq:
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'inline; filename="{nome}"')
                self.send_header("Content-Length", str(arq.length))
                self.end_headers()
                self.wfile.write(arq.read())
                return
            pasta = CFG.PDF_FOLDER
            caminho = os.path.join(pasta, nome) if pasta else ""
            if caminho and os.path.isfile(caminho):
                with open(caminho, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404, f"PDF nao encontrado: {nome}")
        except Exception as e:
            self.send_error(500, str(e))

    def log_message(self, format, *args):
        pass


@st.cache_resource
def iniciar_servidor_pdf():
    try:
        srv = HTTPServer(("0.0.0.0", CFG.PDF_SERVER_PORT), _GridFSHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return True
    except OSError:
        return True


def link_pdf(arquivo: str, pagina: int, termo: str = "") -> str:
    url = f"http://localhost:{CFG.PDF_SERVER_PORT}/{quote(arquivo)}#page={pagina}"
    if termo:
        palavras = termo.strip().split()[:3]
        url += f"&search={quote(' '.join(palavras))}"
    return (f'<a href="{url}" target="_blank" style="text-decoration:none">'
            f'📄 <b>{arquivo}</b> — Página {pagina}</a>')


def links_fontes(resultados: list, termo: str = "") -> str:
    if not resultados:
        return ""
    vistos, links = set(), []
    for r in resultados:
        a = r.get("metadados", {}).get("arquivo", "")
        p = r.get("metadados", {}).get("pagina", 0)
        k = f"{a}_{p}"
        if a and k not in vistos:
            vistos.add(k)
            links.append(link_pdf(a, p, termo))
    if not links:
        return ""
    h = ("<div style='margin-top:10px;padding:10px;background:#f8f9fa;"
         "border-radius:8px'><b>📎 Fontes — clique para abrir o PDF:</b><br>")
    for l in links:
        h += f"<div style='margin:6px 0 6px 16px'>{l}</div>"
    return h + "</div>"


def extrair_termos_reais(destaques: list) -> str:
    termos = []
    for tr in destaques:
        termos.extend(re.findall(r'\*\*(.+?)\*\*', tr))
    vistos = []
    for t in termos:
        if t.lower() not in [v.lower() for v in vistos]:
            vistos.append(t)
        if len(vistos) >= 3:
            break
    return " ".join(vistos)


def render_timings(timings: list) -> None:
    """Renderiza tabela de tempo de execucao de cada ferramenta."""
    if not timings:
        return
    total_ms = sum(t["tempo_ms"] for t in timings)
    with st.expander(f"⏱️ Tempo por ferramenta ({len(timings)} chamadas, {total_ms}ms total)"):
        for i, t in enumerate(timings, 1):
            nome = t.get("ferramenta", "?")
            ms = t.get("tempo_ms", 0)
            ok = t.get("sucesso", True)
            icone = "✅" if ok else "❌"
            # Colunas: ferramenta | barra de tempo | ms
            largura_pct = min(int(ms / max(total_ms, 1) * 100), 100)
            cor = "#22c55e" if ms < 500 else "#eab308" if ms < 2000 else "#ef4444"
            barra = (f"<div style='background:#f1f5f9;border-radius:4px;"
                     f"width:100%;height:18px;position:relative'>"
                     f"<div style='background:{cor};border-radius:4px;"
                     f"width:{largura_pct}%;height:100%'></div></div>")
            c1, c2, c3 = st.columns([3, 6, 1])
            with c1:
                st.markdown(f"{icone} `{nome}`")
            with c2:
                st.markdown(barra, unsafe_allow_html=True)
            with c3:
                st.markdown(f"**{ms}ms**")
            if not ok and t.get("erro"):
                st.caption(f"   ↳ {t['erro']}")


# =====================================================================
# HELPERS LLM
# =====================================================================

def get_system_prompt():
    return carregar_prompt("system_prompt_agente") or DEFAULT_PROMPT


@st.cache_resource
def get_memory():
    return MemorySaver()


@st.cache_resource
def criar_agente_claude(_sp, _mem):
    try:
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=CFG.ANTHROPIC_MODEL,
                             api_key=CFG.ANTHROPIC_API_KEY,
                             temperature=0.1, max_tokens=4000,
                             max_retries=5, timeout=120)
        return create_react_agent(model=llm, tools=TODAS_FERRAMENTAS,
                                    prompt=_sp, checkpointer=_mem)
    except Exception:
        return None


@st.cache_resource
def criar_agente_gemini(_sp, _mem):
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(model=CFG.GEMINI_MODEL,
                                       google_api_key=CFG.GOOGLE_API_KEY,
                                       temperature=1.0, max_output_tokens=4000,
                                       max_retries=3, timeout=120)
        return create_react_agent(model=llm, tools=TODAS_FERRAMENTAS,
                                    prompt=_sp, checkpointer=_mem)
    except Exception:
        return None


@st.cache_resource
def criar_agente_local(_sp, _mem):
    try:
        llm = ChatOllama(model=CFG.LLM_MODEL, temperature=0.1, num_ctx=8192)
        return create_react_agent(model=llm, tools=TODAS_FERRAMENTAS,
                                    prompt=_sp, checkpointer=_mem)
    except Exception:
        return None


def criar_fallback(sp):
    try:
        llm = ChatOllama(model=CFG.LLM_MODEL, temperature=0.1, num_ctx=8192)
        return create_react_agent(model=llm, tools=TODAS_FERRAMENTAS,
                                    prompt=sp, checkpointer=MemorySaver())
    except Exception:
        return None


def _str_resp(resp):
    c = resp.content if hasattr(resp, 'content') else resp
    if isinstance(c, list):
        return "\n".join(p.get("text", str(p)) if isinstance(p, dict) else str(p)
                          for p in c)
    return str(c)


def extrair_resposta(res):
    for msg in reversed(res.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            c = msg.content
            if isinstance(c, list):
                return "\n".join(p.get("text", str(p)) if isinstance(p, dict) else str(p)
                                  for p in c)
            return c
    return "Nao foi possivel gerar resposta."


def extrair_ferramentas(res):
    u = []
    for msg in res.get("messages", []):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                u.append({"ferramenta": tc["name"], "parametros": tc["args"]})
    return u


def invocar_llm(prompt, modelo):
    if modelo == "Claude" and CFG.ANTHROPIC_API_KEY:
        from langchain_anthropic import ChatAnthropic
        return _str_resp(ChatAnthropic(
            model=CFG.ANTHROPIC_MODEL, api_key=CFG.ANTHROPIC_API_KEY,
            temperature=0.1, max_tokens=2000).invoke(prompt))
    elif modelo == "Gemini" and CFG.GOOGLE_API_KEY:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return _str_resp(ChatGoogleGenerativeAI(
            model=CFG.GEMINI_MODEL, google_api_key=CFG.GOOGLE_API_KEY,
            temperature=1.0, max_output_tokens=2000).invoke(prompt))
    else:
        return _str_resp(ChatOllama(model=CFG.LLM_MODEL,
                                     temperature=0.1, num_ctx=8192).invoke(prompt))


def construir_historico(msgs, pergunta, max_t=4):
    ms = []
    hist = [m for m in msgs if m["role"] in ("user", "assistant")]
    for m in hist[-(max_t * 2):]:
        if m["role"] == "user":
            ms.append(HumanMessage(content=m["content"]))
        else:
            ms.append(AIMessage(content=m["content"][:1500]))
    ms.append(HumanMessage(content=pergunta))
    return ms


def eh_cumprimento(t):
    p = t.lower().strip().rstrip("!?.").strip()
    return (p in ["bom dia", "boa tarde", "boa noite", "ola", "oi", "hey",
                   "tudo bem", "como vai", "obrigado", "obrigada", "valeu",
                   "brigado"] or len(p) < 8)


def responder_cumprimento(t):
    p = t.lower().strip()
    if "bom dia" in p:
        return "Bom dia! Sou o assistente da Casa Civil do DF. Como posso ajudar?"
    if "boa tarde" in p:
        return "Boa tarde! Estou a disposicao para consultas ao DODF."
    if "boa noite" in p:
        return "Boa noite! Posso ajudar com consultas ao Diario Oficial."
    if any(x in p for x in ["obrigado", "obrigada", "valeu"]):
        return "De nada! Estou a disposicao."
    if "tudo bem" in p:
        return "Tudo bem! Estou pronto para ajudar."
    return "Ola! Sou o assistente da Casa Civil do DF. Qual sua pergunta?"


# =====================================================================
# ROTEAMENTO DE CONTAGEM/LISTAGEM -> consultar_atos (Modo Rapido)
# =====================================================================

_RE_ANO = re.compile(r"(19|20)\d{2}")
_GATILHO_TIPO = {
    "nomea": "nomeacao", "nomead": "nomeacao",
    "exoner": "exoneracao",
    "design": "designacao",
    "dispens": "dispensacao",
}
_INTENCAO_CONTAGEM = ("quant", "liste", "listar", "relacion", "todos os",
                      "todas as", "quais ", "quem foi", "quem foram")


def _eh_contagem_atos(pergunta: str) -> bool:
    """True se a pergunta pede contagem/listagem de atos de pessoal."""
    p = pergunta.lower()
    tem_intencao = any(k in p for k in _INTENCAO_CONTAGEM)
    tem_gatilho = any(g in p for g in _GATILHO_TIPO)
    return tem_intencao and tem_gatilho


def _filtros_atos(pergunta: str) -> dict:
    """Extrai tipo_ato, ano e mes da pergunta (heuristica deterministica)."""
    p = pergunta.lower()
    tipo = ""
    for gat, tc in _GATILHO_TIPO.items():
        if gat in p:
            tipo = tc
            break
    ano = ""
    m = _RE_ANO.search(p)
    if m:
        ano = m.group(0)
    mes = ""
    for nome_mes in _MESES:
        if nome_mes in p:
            mes = nome_mes
            break
    return {"tipo_ato": tipo, "ano": ano, "mes": mes}


def pipeline_rapido(pergunta, hist, usar_cache, modelo):
    if eh_cumprimento(pergunta):
        return responder_cumprimento(pergunta), [], False, []

    t0 = time.time()
    vetor = gerar_embedding(pergunta)
    ms_emb = int((time.time() - t0) * 1000)
    from tools_dodf import _timings_atual
    _timings_atual.append({"ferramenta": "embedding_query",
                           "tempo_ms": ms_emb, "sucesso": True})

    if usar_cache:
        t0 = time.time()
        rc = verificar_cache(pergunta, vetor=vetor)
        ms_cache = int((time.time() - t0) * 1000)
        _timings_atual.append({"ferramenta": "cache_semantico",
                               "tempo_ms": ms_cache, "sucesso": True})
        if rc:
            return rc, [], True, []

    # Roteamento analitico: pergunta de contagem/listagem -> query estruturada.
    # Gatilho barato (palavra de ato) evita custo de LLM em perguntas comuns;
    # com gatilho, o interpretador LLM extrai os filtros (inclusive o nome).
    if CFG.ATOS_EXTRACTION_ENABLED and any(g in pergunta.lower()
                                           for g in _GATILHO_TIPO):
        filtros = interpretar(pergunta)
        if filtros is None and _eh_contagem_atos(pergunta):
            filtros = _filtros_atos(pergunta)  # fallback sem LLM
        if filtros:
            params = {k: filtros.get(k, "") for k in
                      ("nome_pessoa", "tipo_ato", "cargo", "orgao", "ano", "mes")}
            t0 = time.time()
            resp = _consultar_atos(**params)
            ms_atos = int((time.time() - t0) * 1000)
            _timings_atual.append({"ferramenta": "consulta_analitica",
                                   "tempo_ms": ms_atos, "sucesso": True})
            salvar_cache(pergunta, resp, ["consulta_analitica"], modelo,
                         vetor=vetor)
            return resp, [{"ferramenta": "consulta_analitica",
                           "parametros": params}], False, []

    res = busca_rapida_paralela(pergunta, vetor, limite=6)

    if not res:
        r = "Nao encontrei resultados no DODF."
        salvar_cache(pergunta, r, [], modelo, vetor=vetor)
        return r, [{"ferramenta": "busca_rapida_paralela",
                     "parametros": {"consulta": pergunta}}], False, []

    ctx = ""
    for i, r in enumerate(res, 1):
        a = r.get("metadados", {}).get("arquivo", "?")
        p = r.get("metadados", {}).get("pagina", "?")
        ctx += f"\n[TRECHO {i} - Fonte: {a}, Pagina {p}]\n{r.get('texto', '')[:600]}\n"
    hc = ""
    if hist:
        for m in hist[-4:]:
            hc += f"{'Usuario' if m['role'] == 'user' else 'Assistente'}: {m['content'][:200]}\n"
        hc = f"\nHISTORICO:\n{hc}\n"
    try:
        t0 = time.time()
        resp = invocar_llm(
            f"{PROMPT_RAPIDO}\n{hc}\nTRECHOS:\n{ctx}\n\nPERGUNTA: {pergunta}\n\nRESPOSTA:",
            modelo)
        ms_llm = int((time.time() - t0) * 1000)
        _timings_atual.append({"ferramenta": f"llm_{modelo.lower()}",
                               "tempo_ms": ms_llm, "sucesso": True})
    except Exception as e:
        resp = f"Erro: {e}"
    salvar_cache(pergunta, resp, ["busca_rapida_paralela"], modelo, vetor=vetor)
    return resp, [{"ferramenta": "busca_rapida_paralela",
                   "parametros": {"consulta": pergunta}}], False, res


def ts_fmt(ts):
    return ts.strftime("%d/%m/%Y %H:%M:%S") if isinstance(ts, datetime) else str(ts)


# =====================================================================
# PAGINA: BUSCA TEXTUAL
# =====================================================================

def pagina_busca():
    cabecalho("Busca Textual no Diário Oficial",
              "Busca direta — fuzzy, fonética e stemming (sem IA)")
    consulta = st.text_input("🔍 Buscar no Diário Oficial:",
                              placeholder="Ex: Ibaneis Rocha, nomeação secretário...")

    with st.sidebar:
        marca_sidebar("Busca Textual")
        max_r = st.slider("Máx resultados:", 5, 50, 20)
        st.divider()
        st.caption("✅ Fuzzy | ✅ Fonético | ✅ Normalização | ✅ Stemming | ✅ Highlights")

    if consulta:
        t0 = time.time()
        with st.spinner("Buscando..."):
            t1 = time.time()
            total = busca_textual_contagem(consulta)
            ms_count = int((time.time() - t1) * 1000)
            t1 = time.time()
            res = busca_textual_direta(consulta, limite=max_r)
            ms_search = int((time.time() - t1) * 1000)
        ms = int((time.time() - t0) * 1000)

        if res and "erro" in res[0]:
            st.error(f"Erro: {res[0]['erro']}")
            return

        st.markdown(f"**{total:,} trechos** — exibindo {min(len(res), max_r)} ({ms}ms total)")
        st.caption(f"⏱️ Contagem: {ms_count}ms | Busca: {ms_search}ms")
        st.divider()

        for i, r in enumerate(res, 1):
            arq = r.get("metadados", {}).get("arquivo", "?")
            pag = r.get("metadados", {}).get("pagina", "?")
            score = r.get("score", 0)
            destaques = r.get("trechos_destaque", [])
            texto = r.get("texto", "")

            c1, c2, c3 = st.columns([1, 8, 2])
            with c1:
                st.markdown(f"### {i}")
            with c2:
                st.markdown(f"**{arq}** — Página {pag}")
            with c3:
                st.caption(f"Score: {score:.2f}")

            if destaques:
                tr = destaques[0]
                if len(tr) > 200:
                    tr = tr[:200].rsplit(" ", 1)[0] + "..."
                st.markdown(f"> {tr}")
            else:
                frases = re.split(r'[.!?\n]', texto)
                fm = next((f.strip() for f in frases
                            if any(t.lower() in f.lower() for t in consulta.split())),
                           texto[:150])
                if len(fm) > 200:
                    fm = fm[:200] + "..."
                for t in consulta.split():
                    fm = re.sub(f'({re.escape(t)})', r'**\1**', fm,
                                 flags=re.IGNORECASE)
                st.markdown(f"> {fm}")

            with st.expander("Ver texto completo"):
                st.text(texto)

            termo_real = extrair_termos_reais(destaques) if destaques else consulta
            st.markdown(link_pdf(arq, pag, termo_real), unsafe_allow_html=True)
            st.divider()


# =====================================================================
# PAGINA: CHAT
# =====================================================================

def pagina_chat():
    cabecalho("Assistente Inteligente do DODF",
              "Pergunte sobre decretos, portarias, nomeações e mais")

    with st.sidebar:
        marca_sidebar("Assistente DODF")

        ops, mp = [], {}
        if CFG.ANTHROPIC_API_KEY:
            ops.append("Claude (Anthropic)")
            mp["Claude (Anthropic)"] = "Claude"
        if CFG.GOOGLE_API_KEY:
            ops.append("Gemini 3 Pro (Google)")
            mp["Gemini 3 Pro (Google)"] = "Gemini"
        ops.append(f"Local ({CFG.LLM_MODEL})")
        mp[f"Local ({CFG.LLM_MODEL})"] = "Local"
        mod = mp[st.radio("Modelo:", ops, index=0)]

        st.divider()
        rapido = "Rapido" in st.radio("Modo:",
                                       ["Rapido (~3s)", "Agente (~10-15s)"],
                                       index=0)
        st.divider()
        usar_cache = "Cache" in st.radio("Cache:",
                                          ["Cache + Documentos", "Documentos direto"],
                                          index=0)
        st.divider()
        if st.button("🔄 Nova conversa"):
            st.session_state.msgs = []
            st.session_state.thread_id = os.urandom(8).hex()
            st.rerun()
        st.caption(f"Perguntas: {len([m for m in st.session_state.get('msgs', []) if m['role'] == 'user'])}")

    for k, v in [("msgs", []), ("thread_id", os.urandom(8).hex()),
                  ("last_resp", None), ("last_perg", None)]:
        if k not in st.session_state:
            st.session_state[k] = v

    if not st.session_state.msgs:
        h = carregar_historico(st.session_state.thread_id)
        if h:
            st.session_state.msgs = h

    agente = None
    if not rapido:
        sp, mem = get_system_prompt(), get_memory()
        agente = {"Claude": criar_agente_claude,
                   "Gemini": criar_agente_gemini,
                   "Local": criar_agente_local}[mod](sp, mem)

    for m in st.session_state.msgs:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("links_html"):
                st.markdown(m["links_html"], unsafe_allow_html=True)
            if m.get("ferramentas"):
                with st.expander("Ferramentas chamadas"):
                    for f in m["ferramentas"]:
                        st.caption(f"🔧 {f['ferramenta']}({f['parametros']})")
            if m.get("timings"):
                render_timings(m["timings"])

    if st.session_state.last_resp:
        c1, c2, _ = st.columns([1, 1, 10])
        with c1:
            if st.button("👍", key="fu"):
                salvar_feedback(st.session_state.thread_id,
                                 st.session_state.last_perg,
                                 st.session_state.last_resp, "positivo")
                atualizar_feedback_auditoria(st.session_state.thread_id,
                                              st.session_state.last_perg,
                                              "positivo")
                st.toast("Obrigado!")
        with c2:
            if st.button("👎", key="fd"):
                salvar_feedback(st.session_state.thread_id,
                                 st.session_state.last_perg,
                                 st.session_state.last_resp, "negativo")
                atualizar_feedback_auditoria(st.session_state.thread_id,
                                              st.session_state.last_perg,
                                              "negativo")
                st.toast("Registrado!")

    if pergunta := st.chat_input("Pergunte sobre o Diário Oficial do DF..."):
        with st.chat_message("user"):
            st.markdown(pergunta)
        st.session_state.msgs.append({"role": "user", "content": pergunta})

        with st.chat_message("assistant"):
            t0 = time.time()
            ch = False
            ferr = []
            erro = None
            res_busca = []
            lh = ""

            # Reseta o tracker de timings ANTES de cada pergunta
            reset_timings()

            if rapido:
                with st.spinner(f"Buscando ({mod})..."):
                    resposta, ferr, ch, res_busca = pipeline_rapido(
                        pergunta, st.session_state.msgs[:-1], usar_cache, mod)
            else:
                if not agente:
                    resposta = f"Agente {mod} indisponivel."
                else:
                    rc = verificar_cache(pergunta) if usar_cache else None
                    if rc:
                        resposta = rc
                        ch = True
                    else:
                        with st.spinner(f"Agente ({mod})..."):
                            try:
                                ms = construir_historico(st.session_state.msgs[:-1], pergunta)
                                t1 = time.time()
                                r = agente.invoke(
                                    {"messages": ms},
                                    config={"configurable": {"thread_id": st.session_state.thread_id}})
                                ms_agente = int((time.time() - t1) * 1000)
                                from tools_dodf import _timings_atual
                                _timings_atual.append({
                                    "ferramenta": f"agente_{mod.lower()}_total",
                                    "tempo_ms": ms_agente, "sucesso": True})
                                resposta = extrair_resposta(r)
                                ferr = extrair_ferramentas(r)
                            except Exception as e:
                                err = str(e).lower()
                                if mod != "Local" and any(x in err for x in
                                    ["overloaded", "529", "429", "rate", "quota"]):
                                    st.warning(f"⚠️ {mod} indisponivel. Fallback local...")
                                    try:
                                        fb = criar_fallback(get_system_prompt())
                                        r2 = fb.invoke(
                                            {"messages": construir_historico(st.session_state.msgs[:-1], pergunta)},
                                            config={"configurable": {"thread_id": st.session_state.thread_id + "_fb"}})
                                        resposta = extrair_resposta(r2)
                                        ferr = extrair_ferramentas(r2)
                                        mod = f"{CFG.LLM_MODEL} (fallback)"
                                    except Exception as e2:
                                        resposta = f"Erro: {e2}"
                                        erro = str(e2)
                                else:
                                    resposta = f"Erro: {e}"
                                    erro = str(e)
                        salvar_cache(pergunta, resposta,
                                       [f["ferramenta"] for f in ferr], mod)

            if isinstance(resposta, list):
                resposta = "\n".join(str(p) for p in resposta)
            elif not isinstance(resposta, str):
                resposta = str(resposta)

            ms_t = int((time.time() - t0) * 1000)
            ok = "nao encontrei" not in resposta.lower() and erro is None

            timings_capturados = get_timings()

            registrar_metrica(st.session_state.thread_id, pergunta,
                                [f["ferramenta"] for f in ferr], mod, ms_t, ch, ok)
            turno = len([m for m in st.session_state.msgs if m["role"] == "user"])
            ctx_a = [{"role": m["role"], "content": m["content"][:500]}
                      for m in st.session_state.msgs[:-1]]
            registrar_auditoria(
                st.session_state.thread_id, pergunta, resposta, mod, ferr, ms_t, ch,
                f"{'Rapido' if rapido else 'Agente'}|{'Cache' if usar_cache else 'Direto'}",
                turno, ctx_a, ok, erro)

            st.markdown(resposta)
            if res_busca:
                lh = links_fontes(res_busca, pergunta)
                if lh:
                    st.markdown(lh, unsafe_allow_html=True)
            elif not ch:
                fontes = re.findall(
                    r'(?:Fonte|fonte)[:\s]*([^\s,]+\.pdf)[,\s]*(?:[Pp]ágina?\s*)?(\d+)?',
                    resposta)
                if fontes:
                    lh = ("<div style='margin-top:10px;padding:10px;"
                          "background:#f8f9fa;border-radius:8px'><b>📎 Fontes:</b><br>")
                    for a, p in fontes:
                        lh += (f"<div style='margin:6px 0 6px 16px'>"
                               f"{link_pdf(a, int(p) if p else 1)}</div>")
                    lh += "</div>"
                    st.markdown(lh, unsafe_allow_html=True)

            st.caption(f"{'⚡ Cache' if ch else '⏱️'} {ms_t}ms total{'' if ch else f' ({mod})'}")

            if ferr:
                with st.expander(f"Ferramentas chamadas ({len(ferr)})"):
                    for i, f in enumerate(ferr, 1):
                        st.caption(f"🔧 **{i}. {f['ferramenta']}** — {f['parametros']}")

            # NOVO: Tabela de tempo por ferramenta
            if timings_capturados:
                render_timings(timings_capturados)

        st.session_state.msgs.append({"role": "assistant", "content": resposta,
                                       "ferramentas": ferr, "cache_hit": ch,
                                       "links_html": lh,
                                       "timings": timings_capturados})
        st.session_state.last_resp = resposta
        st.session_state.last_perg = pergunta
        salvar_historico(st.session_state.thread_id,
                          [{"role": m["role"], "content": m["content"],
                            "timestamp": time.time()} for m in st.session_state.msgs])


# =====================================================================
# PAGINA: UPLOAD E GESTAO DE PDFs
# =====================================================================

def pagina_upload():
    cabecalho("Upload e Gestão de PDFs",
              "Envie e indexe novos documentos do Diário Oficial")

    with st.sidebar:
        marca_sidebar("Gestão de PDFs")
        st.caption(f"Embedding: {CFG.VOYAGE_EMBEDDING_MODEL}")
        st.caption(f"Dimensão: {CFG.VOYAGE_EMBEDDING_DIMENSION}d")

    st.subheader("📤 Enviar novos PDFs")
    arquivos = st.file_uploader("Arraste PDFs aqui:", type=["pdf"],
                                 accept_multiple_files=True)

    if arquivos and st.button("Processar PDFs", type="primary"):
        for arq in arquivos:
            with st.spinner(f"Processando {arq.name}..."):
                data = arq.read()
                progresso = st.progress(0, text=f"Processando {arq.name}...")

                def callback(feitos, total, pct):
                    progresso.progress(pct / 100,
                                        text=f"{arq.name}: {feitos}/{total} chunks ({pct}%)")

                resultado = processar_pdf_bytes(arq.name, data,
                                                  origem="upload_web",
                                                  callback=callback)

                if resultado["status"] == "processado":
                    st.success(f"✅ {arq.name} — {resultado['paginas']} páginas, "
                                 f"{resultado['chunks']} chunks")
                elif resultado["status"] == "ja_processado":
                    st.info(f"ℹ️ {arq.name} — já existe na base")
                else:
                    st.error(f"❌ {arq.name} — {resultado.get('erro', 'erro')}")

    st.divider()
    st.subheader("📁 PDFs na Base")

    pdfs = listar_pdfs()
    if not pdfs:
        st.info("Nenhum PDF registrado.")
        return

    total_pdfs = len(pdfs)
    total_chunks = sum(p.get("total_chunks", 0) for p in pdfs)
    total_bytes = sum(p.get("tamanho_bytes", 0) for p in pdfs)
    c1, c2, c3 = st.columns(3)
    c1.metric("PDFs", total_pdfs)
    c2.metric("Chunks", f"{total_chunks:,}")
    c3.metric("Tamanho", f"{total_bytes / 1024 / 1024:.1f} MB")

    st.divider()

    for pdf in pdfs:
        nome = pdf.get("nome_arquivo", "?")
        status = pdf.get("status", "?")
        pags = pdf.get("total_paginas", 0)
        chunks = pdf.get("total_chunks", 0)
        origem = pdf.get("enviado_por", "?")
        data = pdf.get("data_upload")
        data_str = ts_fmt(data) if data else "?"

        icone = {"processado": "✅", "processando": "⏳",
                  "pendente": "🔵", "erro": "❌"}.get(status, "❓")

        with st.expander(f"{icone} {nome} — {pags} pgs, {chunks} chunks"):
            c1, c2, c3, c4 = st.columns(4)
            c1.caption(f"Status: {status}")
            c2.caption(f"Origem: {origem}")
            c3.caption(f"Upload: {data_str}")
            c4.caption(f"Hash: {pdf.get('hash_md5', '?')[:8]}...")

            erro = pdf.get("erro")
            if erro:
                st.error(f"Erro: {erro}")

            col_view, col_del = st.columns([1, 1])
            with col_view:
                url = f"http://localhost:{CFG.PDF_SERVER_PORT}/{quote(nome)}"
                st.markdown(f"[📄 Abrir PDF]({url})")
            with col_del:
                if st.button("🗑️ Excluir", key=f"del_{pdf.get('hash_md5', '')}"):
                    excluir_pdf(pdf.get("hash_md5", ""))
                    st.success(f"Excluído: {nome}")
                    st.rerun()


# =====================================================================
# PAGINA: AUDITORIA
# =====================================================================

def pagina_auditoria():
    cabecalho("Auditoria de Consultas",
              "Métricas de uso, performance e feedback")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        dias = st.selectbox("Periodo:", [1, 7, 30, 90, 365], index=1)
    with c2:
        fm = st.selectbox("Modelo:",
                           ["Todos", "Claude", "Gemini", CFG.LLM_MODEL], index=0)
    with c3:
        fs = st.selectbox("Status:", ["Todos", "Sucesso", "Erro"], index=0)
    with c4:
        ff = st.selectbox("Feedback:",
                           ["Todos", "Positivo", "Negativo", "Sem"], index=0)

    q = {"timestamp": {"$gte": datetime.now() - timedelta(days=dias)}}
    if fm != "Todos":
        q["modelo"] = {"$regex": fm, "$options": "i"}
    if fs == "Sucesso":
        q["sucesso"] = True
    elif fs == "Erro":
        q["sucesso"] = False
    if ff == "Positivo":
        q["feedback.avaliacao"] = "positivo"
    elif ff == "Negativo":
        q["feedback.avaliacao"] = "negativo"
    elif ff == "Sem":
        q["feedback"] = None

    b = st.text_input("🔍 Buscar:", "")
    if b:
        q["$or"] = [{"pergunta": {"$regex": b, "$options": "i"}},
                    {"resposta": {"$regex": b, "$options": "i"}}]

    st.divider()
    stats = estatisticas_auditoria()
    if stats:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total", stats["total_interacoes"])
        c2.metric("Sessoes", stats["sessoes_unicas"])
        c3.metric("👍", stats["feedback_positivo"])
        c4.metric("👎", stats["feedback_negativo"])
        c5.metric("Tempo", f"{stats['tempo_medio_ms']}ms")
    else:
        st.info("Sem dados.")

    st.divider()
    regs = consultar_auditoria(filtros=q, limite=100)
    if not regs:
        st.info("Nenhum registro.")
        return
    st.subheader(f"Registros ({len(regs)})")
    for r in regs:
        ic = "✅" if r.get("sucesso", True) else "❌"
        if r.get("cache_hit"):
            ic += " ⚡"
        fb = r.get("feedback")
        if fb:
            ic += " 👍" if fb.get("avaliacao") == "positivo" else " 👎" if fb.get("avaliacao") == "negativo" else ""
        with st.expander(f"{ic} [{ts_fmt(r.get('timestamp', ''))}] {r.get('pergunta', '')[:80]}"):
            c1, c2, c3 = st.columns(3)
            c1.caption(f"Modelo: {r.get('modelo', '?')}")
            c2.caption(f"Tempo: {r.get('tempo_resposta_ms', 0)}ms")
            c3.caption(f"Modo: {r.get('modo_busca', '?')}")
            st.info(r.get("pergunta", ""))
            st.success(r.get("resposta", ""))


# =====================================================================
# MAIN
# =====================================================================

def main():
    st.set_page_config(page_title="Casa Civil DF - DODF",
                        page_icon="🏛️", layout="wide")
    aplicar_tema()
    iniciar_servidor_pdf()

    pag = st.sidebar.radio("Navegação",
                            ["💬 Chat (com IA)", "🔍 Busca Textual",
                             "📤 Upload PDFs", "📋 Auditoria"], index=0)

    if pag.startswith("💬"):
        pagina_chat()
    elif pag.startswith("🔍"):
        pagina_busca()
    elif pag.startswith("📤"):
        pagina_upload()
    else:
        pagina_auditoria()


if __name__ == "__main__":
    main()
