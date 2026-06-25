"""
extrator_atos.py — Extracao estruturada de atos (Fase 1)
=========================================================
Estrategia HIBRIDA:
  1. Regex deterministico (rapido, offline) — primeira passada.
  2. LLM de reforco — so quando ha gatilho de ato mas o regex nao extraiu nada.

Expoe: extrair_atos(), normalizar(), tipo_canonico()
"""

import re
import json
import unicodedata
from datetime import datetime

from config import CFG


# =====================================================================
# NORMALIZACAO E TIPOS
# =====================================================================

def normalizar(s: str) -> str:
    """minusculas, sem acento — para indexar/buscar nomes."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def tipo_canonico(s: str) -> str:
    """Mapeia variacoes ('nomear', 'nomeacoes'...) para o tipo canonico."""
    v = normalizar(s)
    if v.startswith("nome"):
        return "nomeacao"
    if v.startswith("exoner"):
        return "exoneracao"
    if v.startswith("design"):
        return "designacao"
    if v.startswith("dispens"):
        return "dispensacao"
    return v or "outro"


# =====================================================================
# REGEX
# =====================================================================

_MAIUSC = "A-ZÁÉÍÓÚÃÕÂÊÔÇ"
_TRIGGER = re.compile(
    r"NOMEAR|EXONERAR|DESIGNAR|DISPENSAR|nomead|exonerad|designad|dispensad",
    re.IGNORECASE)

_RE_ATOS = [
    re.compile(
        r"(NOMEAR|EXONERAR|DESIGNAR|DISPENSAR)\s*,?\s*(?:a\s+pedido\s*,?\s*)?"
        rf"([{_MAIUSC}][{_MAIUSC}\s]{{6,60}}?)"
        r"(?:\s*,|\s+para|\s+do\s+Cargo|\s+da\s+Função|\s+matrícula)"),
    re.compile(
        r"(nomead[oa]|exonerad[oa]|designad[oa]|dispensad[oa])\s*,?\s*"
        rf"([{_MAIUSC}][{_MAIUSC}\s]{{6,60}}?)"
        r"(?:\s*,|\s+para|\s+do\s+Cargo)"),
]
_RE_LIMPA = re.compile(r"\s+(DE|DA|DO|DOS|DAS|E|PARA|A|O)\s*$")
_RE_CARGO = re.compile(
    r"(?:Cargo\s+(?:em\s+Comissão|de\s+Natureza\s+Especial)|"
    r"Função\s+de\s+Confiança)[,\s]+(?:Símbolo\s+)?([^,\n]{5,80})")
_RE_ORGAO = re.compile(
    r"(?:da|do)\s+((?:Secretaria|Administração Regional|Subsecretaria|"
    r"Diretoria|Casa Civil|Procuradoria)[^,\n\.]{5,100})")
_RE_DATA_ARQ = re.compile(r"(\d{2})-(\d{2})-(\d{4})")


def _data_de_arquivo(arquivo: str):
    """Extrai (data, ano, mes) do nome 'DODF 015 22-01-2025 INTEGRA.pdf'."""
    m = _RE_DATA_ARQ.search(arquivo or "")
    if not m:
        return None, None, None
    d, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(ano, mes, d), ano, mes
    except ValueError:
        return None, ano, mes


def _novo_ato(nome, tipo, cargo, orgao, arquivo, pagina, hash_arq,
              fonte, metodo):
    data, ano, mes = _data_de_arquivo(arquivo)
    return {
        "nome": nome.title(),
        "nome_normalizado": normalizar(nome),
        "tipo_ato": tipo,
        "cargo": (cargo or "").strip(),
        "orgao": (orgao or "").strip(),
        "data": data, "ano": ano, "mes": mes,
        "arquivo": arquivo, "pagina": pagina,
        "hash_arquivo": hash_arq,
        "fonte_texto": fonte[:300],
        "metodo_extracao": metodo,
        "criado_em": datetime.now(),
    }


def extrair_regex(texto, arquivo, pagina, hash_arq) -> list:
    atos, vistos = [], set()
    for pat in _RE_ATOS:
        for m in pat.finditer(texto):
            tipo = tipo_canonico(m.group(1))
            nome = _RE_LIMPA.sub("", m.group(2).strip()).strip()
            if len(nome) <= 6 or " " not in nome:
                continue
            chave = (normalizar(nome), tipo)
            if chave in vistos:
                continue
            vistos.add(chave)
            pos = texto.upper().find(nome.upper())
            ctx = texto[max(0, pos):pos + 400]
            cm, om = _RE_CARGO.search(ctx), _RE_ORGAO.search(ctx)
            atos.append(_novo_ato(
                nome, tipo, cm.group(1) if cm else "",
                om.group(1) if om else "", arquivo, pagina, hash_arq,
                ctx, "regex"))
    return atos


def extrair_atos(texto, arquivo, pagina, hash_arq) -> list:
    """Hibrido: regex; LLM apenas se ha gatilho mas regex falhou."""
    atos = extrair_regex(texto, arquivo, pagina, hash_arq)
    if (not atos and _TRIGGER.search(texto)
            and CFG.ATOS_LLM_ENABLED and CFG.ANTHROPIC_API_KEY):
        atos = extrair_llm(texto, arquivo, pagina, hash_arq)
    return atos


# =====================================================================
# REFORCO POR LLM (so quando regex falha em trecho com gatilho)
# =====================================================================

_PROMPT_LLM = (
    "Extraia do texto do Diario Oficial os atos de pessoal (nomeacao, "
    "exoneracao, designacao, dispensacao). Responda APENAS um array JSON; "
    "cada item: {\"nome\":..., \"tipo_ato\":\"nomeacao|exoneracao|designacao|"
    "dispensacao\", \"cargo\":..., \"orgao\":...}. Se nao houver, retorne []."
    "\n\nTEXTO:\n")


def _parse_json_lista(conteudo: str) -> list:
    if not conteudo:
        return []
    ini, fim = conteudo.find("["), conteudo.rfind("]")
    if ini == -1 or fim == -1 or fim < ini:
        return []
    try:
        dados = json.loads(conteudo[ini:fim + 1])
        return dados if isinstance(dados, list) else []
    except Exception:
        return []


def extrair_llm(texto, arquivo, pagina, hash_arq) -> list:
    """Extracao via Claude — tolerante a falhas (retorna [] em qualquer erro)."""
    try:
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=CFG.ANTHROPIC_MODEL,
                            api_key=CFG.ANTHROPIC_API_KEY,
                            temperature=0, max_tokens=1500, timeout=60)
        resp = llm.invoke(_PROMPT_LLM + texto[:4000])
        conteudo = resp.content if hasattr(resp, "content") else str(resp)
        if isinstance(conteudo, list):
            conteudo = " ".join(str(c) for c in conteudo)
    except Exception:
        return []

    atos, vistos = [], set()
    for item in _parse_json_lista(conteudo):
        if not isinstance(item, dict):
            continue
        nome = (item.get("nome") or "").strip()
        if len(nome) <= 6 or " " not in nome:
            continue
        tipo = tipo_canonico(item.get("tipo_ato") or "")
        chave = (normalizar(nome), tipo)
        if chave in vistos:
            continue
        vistos.add(chave)
        atos.append(_novo_ato(
            nome, tipo, item.get("cargo") or "", item.get("orgao") or "",
            arquivo, pagina, hash_arq, texto, "llm"))
    return atos
