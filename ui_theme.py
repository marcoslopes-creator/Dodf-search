"""
ui_theme.py — Identidade visual MongoDB para o DODF Search
============================================================
Paleta: Spring Green #00ED64 | Evergreen #00684A | Slate #001E2B
Expoe: aplicar_tema(), cabecalho(), marca_sidebar()
"""

import streamlit as st

VERDE = "#00ED64"
VERDE_ESC = "#00684A"
SLATE = "#001E2B"

# Folha MongoDB (SVG inline)
_LEAF = (
    "<svg width='30' height='30' viewBox='0 0 100 100' aria-hidden='true'>"
    "<path fill='#00ED64' d='M50 4 C30 34 26 70 47 94 C49 96 51 96 53 94 "
    "C74 70 70 34 50 4 Z'/>"
    "<path fill='#00684A' d='M50 96 C48 70 49 38 50 12 C51 38 52 70 50 96 Z'/>"
    "</svg>"
)

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #F4F7F6; }

/* ---- Sidebar escura estilo MongoDB ---- */
[data-testid="stSidebar"] { background: #001E2B; }
[data-testid="stSidebar"] * { color: #E8EDEB !important; }
[data-testid="stSidebar"] .stRadio [aria-checked="true"] + div { color: #00ED64 !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.12); }

/* ---- Cabecalho com gradiente ---- */
.dodf-header {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 22px; margin-bottom: 18px;
  background: linear-gradient(135deg, #00684A 0%, #001E2B 100%);
  border-radius: 16px; box-shadow: 0 6px 20px rgba(0,30,43,0.18);
}
.dodf-leaf { background: rgba(255,255,255,0.08); border-radius: 12px;
  padding: 8px; display: flex; }
.dodf-title { color: #fff; font-size: 1.35rem; font-weight: 700; line-height: 1.2; }
.dodf-sub { color: #B8C4C2; font-size: 0.9rem; margin-top: 2px; }

/* ---- Marca da sidebar ---- */
.dodf-brand { display: flex; align-items: center; gap: 10px; padding: 6px 0 12px; }
.dodf-brand .n { color: #fff; font-weight: 700; font-size: 1.05rem; }
.dodf-brand .s { color: #00ED64; font-size: 0.78rem; }

/* ---- Botoes ---- */
.stButton > button {
  background: #00ED64; color: #001E2B; border: none; border-radius: 10px;
  font-weight: 600; padding: 0.5rem 1.1rem; transition: all .15s ease;
}
.stButton > button:hover { background: #00C853; color: #001E2B; transform: translateY(-1px); }

/* ---- Inputs ---- */
.stTextInput input, .stChatInput textarea {
  border-radius: 10px !important; border: 1px solid #D6E0DD !important;
}
.stTextInput input:focus { border-color: #00ED64 !important; box-shadow: 0 0 0 2px rgba(0,237,100,0.2) !important; }

/* ---- Metricas em cartao ---- */
[data-testid="stMetric"] {
  background: #fff; border: 1px solid #E3EAE8; border-radius: 14px;
  padding: 14px 16px; box-shadow: 0 2px 8px rgba(0,30,43,0.05);
}
[data-testid="stMetricValue"] { color: #00684A; }

/* ---- Expanders e chat ---- */
[data-testid="stExpander"] { border: 1px solid #E3EAE8 !important; border-radius: 12px !important; }
[data-testid="stChatMessage"] {
  background: #fff; border: 1px solid #E3EAE8; border-radius: 14px;
  padding: 4px 12px; box-shadow: 0 2px 8px rgba(0,30,43,0.04);
}
h1, h2, h3 { color: #001E2B; }
a { color: #00684A; }
</style>
"""


def aplicar_tema():
    """Injeta o CSS da identidade MongoDB. Chamar uma vez no inicio."""
    st.markdown(_CSS, unsafe_allow_html=True)


def cabecalho(titulo: str, subtitulo: str):
    """Renderiza o cabecalho principal com a folha MongoDB."""
    st.markdown(
        f"<div class='dodf-header'>"
        f"<div class='dodf-leaf'>{_LEAF}</div>"
        f"<div><div class='dodf-title'>{titulo}</div>"
        f"<div class='dodf-sub'>{subtitulo}</div></div></div>",
        unsafe_allow_html=True,
    )


def marca_sidebar(secao: str):
    """Renderiza a marca no topo da sidebar (chamar dentro de st.sidebar)."""
    st.markdown(
        f"<div class='dodf-brand'>{_LEAF}"
        f"<div><div class='n'>Casa Civil DF</div>"
        f"<div class='s'>{secao}</div></div></div>",
        unsafe_allow_html=True,
    )
    st.divider()
