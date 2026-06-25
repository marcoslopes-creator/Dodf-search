"""
ocr.py — OCR de fallback por imagem de pagina (provedor plugavel)
==================================================================
Usado APENAS quando a extracao de texto nativa (PyMuPDF) falha em uma
pagina (ex.: pagina escaneada). Recebe a imagem PNG ja renderizada e
devolve o texto. Tolerante a falhas: retorna '' em qualquer erro.

Provedores:
  - gemini  : usa GOOGLE_API_KEY (ja disponivel; sem dependencia nova)
  - mistral : usa MISTRAL_API_KEY (requer 'pip install mistralai')
"""

import base64

from config import CFG

_PROMPT_OCR = (
    "Transcreva FIELMENTE todo o texto desta pagina do Diario Oficial, em "
    "portugues, preservando a ordem de leitura (colunas da esquerda para a "
    "direita). Nao traduza, nao resuma e nao adicione comentarios. Devolva "
    "apenas o texto transcrito."
)


def _data_uri(png_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def _ocr_gemini(png_bytes: bytes) -> str:
    if not CFG.GOOGLE_API_KEY:
        return ""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage

    llm = ChatGoogleGenerativeAI(model=CFG.GEMINI_MODEL,
                                 google_api_key=CFG.GOOGLE_API_KEY,
                                 temperature=0, max_output_tokens=4000,
                                 timeout=90)
    msg = HumanMessage(content=[
        {"type": "text", "text": _PROMPT_OCR},
        {"type": "image_url",
         "image_url": {"url": _data_uri(png_bytes)}},
    ])
    resp = llm.invoke([msg])
    c = resp.content if hasattr(resp, "content") else resp
    if isinstance(c, list):
        return " ".join(p.get("text", "") if isinstance(p, dict) else str(p)
                        for p in c)
    return str(c)


def _ocr_mistral(png_bytes: bytes) -> str:
    if not CFG.MISTRAL_API_KEY:
        return ""
    try:
        from mistralai import Mistral
    except ImportError:
        print("        OCR mistral indisponivel: rode 'pip install mistralai'",
              flush=True)
        return ""

    client = Mistral(api_key=CFG.MISTRAL_API_KEY)
    resp = client.ocr.process(
        model=CFG.MISTRAL_OCR_MODEL,
        document={"type": "image_url", "image_url": _data_uri(png_bytes)},
    )
    paginas = getattr(resp, "pages", None) or []
    return "\n".join(getattr(p, "markdown", "") or "" for p in paginas)


_PROVEDORES = {"gemini": _ocr_gemini, "mistral": _ocr_mistral}


def ocr_imagem_png(png_bytes: bytes) -> str:
    """Aplica OCR na imagem PNG. Retorna '' em qualquer falha."""
    if not png_bytes:
        return ""
    fn = _PROVEDORES.get(CFG.OCR_PROVIDER)
    if fn is None:
        print(f"        OCR: provedor '{CFG.OCR_PROVIDER}' desconhecido",
              flush=True)
        return ""
    try:
        return (fn(png_bytes) or "").strip()
    except Exception as e:
        print(f"        OCR ({CFG.OCR_PROVIDER}) falhou: {str(e)[:120]}",
              flush=True)
        return ""
