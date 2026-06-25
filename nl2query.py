"""
nl2query.py — Interpretacao de perguntas analiticas (Text-to-Query)
====================================================================
Transforma uma pergunta em linguagem natural em FILTROS estruturados
para a colecao 'atos'. O LLM NAO escreve pipelines MongoDB crus (risco
de injecao/erro): ele apenas extrai parametros conhecidos, e o
_consultar_atos monta e executa a agregacao de forma deterministica.

Saida de interpretar(): dict com as chaves aceitas por _consultar_atos
(nome_pessoa, tipo_ato, cargo, orgao, ano, mes) + 'operacao', ou None
quando a pergunta nao e analitica.
"""

import json

from config import CFG
from extrator_atos import tipo_canonico

_PROMPT = (
    "Voce converte perguntas sobre o Diario Oficial (DODF) em filtros JSON "
    "para consultar atos de pessoal. Responda APENAS um objeto JSON, sem "
    "texto extra, com EXATAMENTE estas chaves:\n"
    '{"analitica": true|false, "operacao": "contar"|"listar", '
    '"nome_pessoa": "", "tipo_ato": "", "cargo": "", "orgao": "", '
    '"ano": "", "mes": ""}\n\n'
    "REGRAS:\n"
    "- analitica=true SOMENTE se a pergunta pede contagem ou listagem de "
    "pessoas nomeadas/exoneradas/designadas/dispensadas.\n"
    "- tipo_ato deve ser um de: nomeacao, exoneracao, designacao, "
    "dispensacao (ou vazio se nao especificado).\n"
    "- nome_pessoa: apenas o nome citado da pessoa do ato (ou vazio).\n"
    "- ano: 4 digitos ou vazio. mes: numero 1-12 ou vazio.\n"
    "- cargo/orgao: termo citado ou vazio.\n\n"
    "EXEMPLOS:\n"
    "P: quantos pedros foram nomeados em 2025\n"
    'R: {"analitica": true, "operacao": "contar", "nome_pessoa": "pedro", '
    '"tipo_ato": "nomeacao", "cargo": "", "orgao": "", "ano": "2025", '
    '"mes": ""}\n'
    "P: liste os exonerados da Secretaria de Saude em maio de 2025\n"
    'R: {"analitica": true, "operacao": "listar", "nome_pessoa": "", '
    '"tipo_ato": "exoneracao", "cargo": "", "orgao": "Secretaria de Saude", '
    '"ano": "2025", "mes": "5"}\n'
    "P: qual o teor do decreto sobre transito\n"
    'R: {"analitica": false, "operacao": "listar", "nome_pessoa": "", '
    '"tipo_ato": "", "cargo": "", "orgao": "", "ano": "", "mes": ""}\n\n'
    "PERGUNTA: "
)


def _texto_resposta(resp) -> str:
    c = resp.content if hasattr(resp, "content") else resp
    if isinstance(c, list):
        return " ".join(p.get("text", str(p)) if isinstance(p, dict) else str(p)
                        for p in c)
    return str(c)


def _chamar_llm(pergunta: str) -> str:
    """Chama Claude (preferencial) ou Gemini. Retorna '' se indisponivel."""
    prompt = _PROMPT + pergunta
    try:
        if CFG.ANTHROPIC_API_KEY:
            from langchain_anthropic import ChatAnthropic
            llm = ChatAnthropic(model=CFG.ANTHROPIC_MODEL,
                                api_key=CFG.ANTHROPIC_API_KEY,
                                temperature=0, max_tokens=400, timeout=30)
            return _texto_resposta(llm.invoke(prompt))
        if CFG.GOOGLE_API_KEY:
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(model=CFG.GEMINI_MODEL,
                                         google_api_key=CFG.GOOGLE_API_KEY,
                                         temperature=0, max_output_tokens=400,
                                         timeout=30)
            return _texto_resposta(llm.invoke(prompt))
    except Exception:
        return ""
    return ""


def _parse_json_obj(conteudo: str) -> dict:
    if not conteudo:
        return {}
    ini, fim = conteudo.find("{"), conteudo.rfind("}")
    if ini == -1 or fim == -1 or fim < ini:
        return {}
    try:
        dados = json.loads(conteudo[ini:fim + 1])
        return dados if isinstance(dados, dict) else {}
    except Exception:
        return {}


def _normalizar(d: dict) -> dict:
    """Sanitiza os campos vindos do LLM para o formato de _consultar_atos."""
    tipo = (d.get("tipo_ato") or "").strip()
    tipo = tipo_canonico(tipo) if tipo else ""
    if tipo == "outro":
        tipo = ""

    ano = str(d.get("ano") or "").strip()
    ano = ano if ano.isdigit() and len(ano) == 4 else ""

    mes = str(d.get("mes") or "").strip()
    mes = mes if mes.isdigit() and 1 <= int(mes) <= 12 else ""

    return {
        "operacao": (d.get("operacao") or "listar").strip().lower(),
        "nome_pessoa": (d.get("nome_pessoa") or "").strip(),
        "tipo_ato": tipo,
        "cargo": (d.get("cargo") or "").strip(),
        "orgao": (d.get("orgao") or "").strip(),
        "ano": ano,
        "mes": mes,
    }


def interpretar(pergunta: str) -> dict:
    """Retorna filtros estruturados ou None se a pergunta nao for analitica."""
    if not pergunta or not pergunta.strip():
        return None
    dados = _parse_json_obj(_chamar_llm(pergunta))
    if not dados or not dados.get("analitica"):
        return None
    return _normalizar(dados)
