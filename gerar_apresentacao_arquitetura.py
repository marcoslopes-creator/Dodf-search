"""Gera o deck tecnico da arquitetura do DODF Search.

Segue o sistema visual "Verde / Navy": paleta de acento unico (00ED64),
tipografia Lexend Deca, grade fixa de cabecalho e os layouts do catalogo.
Uso: ./venv/bin/python gerar_apresentacao_arquitetura.py
"""

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

SAIDA = "DODF-Search-Arquitetura.pptx"

C = {
    "verde": "00ED64", "verde_escuro": "00914B", "verde_onda": "00B050",
    "navy": "001E2B", "navy_card": "0A303D", "navy_borda": "254D57",
    "branco": "FFFFFF", "off_white": "F7FAF9", "zebra": "F2F7F5",
    "verde_claro": "E6F7EF", "borda": "D1DEDA",
    "texto": "233138", "texto_fraco": "5B6C74",
    "texto_claro": "C7DFD8", "texto_claro2": "D2E6E1", "texto_claro3": "DFEEEA",
}

FONTE_BOLD = "Lexend Deca Black"
FONTE_BODY = "Lexend Deca Medium"
FONTE_MONO = "Consolas"

ALINHA = {"esq": PP_ALIGN.LEFT, "centro": PP_ALIGN.CENTER, "dir": PP_ALIGN.RIGHT}


def _cor(token):
    return RGBColor.from_string(C[token])


# =====================================================================
# PRIMITIVAS
# =====================================================================

def fundo(slide, token="off_white"):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = _cor(token)


def onda(slide):
    """Elipse decorativa inferior (equivalente a onda do slide master)."""
    e = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(-2.2), Inches(7.02),
                               Inches(17.8), Inches(3.4))
    e.fill.solid()
    e.fill.fore_color.rgb = _cor("verde_onda")
    e.line.fill.background()
    e.shadow.inherit = False


def logo(slide):
    """Marca vetorial no canto superior direito (folha verde)."""
    s = slide.shapes.add_shape(MSO_SHAPE.TEAR, Inches(12.15), Inches(0.57),
                               Inches(0.53), Inches(0.61))
    s.rotation = 225
    s.fill.solid()
    s.fill.fore_color.rgb = _cor("verde")
    s.line.fill.background()
    s.shadow.inherit = False


def txt(slide, x, y, w, h, texto, tam=12, bold=False, cor="texto",
        align="esq", italico=False, entrelinha=None, ancora=MSO_ANCHOR.TOP,
        espaco_depois=0):
    cx = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = cx.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = ancora
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, linha in enumerate(str(texto).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = ALINHA[align]
        if entrelinha:
            p.line_spacing = entrelinha
        if espaco_depois:
            p.space_after = Pt(espaco_depois)
        r = p.add_run()
        r.text = linha
        r.font.name = FONTE_BOLD if bold else FONTE_BODY
        r.font.size = Pt(tam)
        r.font.bold = bold
        r.font.italic = italico
        r.font.color.rgb = _cor(cor)
    return cx


def bloco_codigo(slide, x, y, w, h, codigo, tam=9):
    """Bloco monoespacado; linhas iniciadas por '#' saem em verde."""
    cx = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = cx.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, linha in enumerate(codigo.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = 1.22
        r = p.add_run()
        r.text = linha if linha.strip() else " "
        r.font.name = FONTE_MONO
        r.font.size = Pt(tam)
        r.font.color.rgb = _cor("verde" if linha.strip().startswith("#")
                                else "texto_claro3")
    return cx


def caixa(slide, x, y, w, h, fill="branco", borda="borda", reto=False,
          sombra=True):
    forma = MSO_SHAPE.RECTANGLE if reto else MSO_SHAPE.ROUNDED_RECTANGLE
    s = slide.shapes.add_shape(forma, Inches(x), Inches(y),
                               Inches(w), Inches(h))
    if not reto:
        s.adjustments[0] = 0.12
    s.fill.solid()
    s.fill.fore_color.rgb = _cor(fill)
    if borda:
        s.line.color.rgb = _cor(borda)
        s.line.width = Pt(0.75)
    else:
        s.line.fill.background()
    s.shadow.inherit = sombra
    s.text_frame.word_wrap = True
    return s


def regua(slide, x=0.65, y=1.86, w=12.03, h=0.03, cor="verde"):
    r = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                               Inches(w), Inches(h))
    r.fill.solid()
    r.fill.fore_color.rgb = _cor(cor)
    r.line.fill.background()
    r.shadow.inherit = False
    return r


def marcador(slide, x, y, lado=0.17):
    m = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x),
                               Inches(y), Inches(lado), Inches(lado))
    m.adjustments[0] = 0.25
    m.fill.solid()
    m.fill.fore_color.rgb = _cor("verde")
    m.line.fill.background()
    m.shadow.inherit = False
    return m


def seta(slide, x, y, w=0.45, h=0.4):
    txt(slide, x, y, w, h, "\u2192", 24, True, "verde", "centro")



def rodape(slide, texto):
    txt(slide, 0.80, 7.07, 11.0, 0.24, texto, 8, False, "navy", "esq",
        italico=True)


def cabecalho(slide, eyebrow, titulo, subtitulo="", escuro=False):
    """Grade fixa: eyebrow + titulo + subtitulo + regua verde."""
    txt(slide, 0.65, 0.35, 5.50, 0.25, eyebrow.upper(), 10, True, "verde")
    txt(slide, 0.65, 0.63, 12.00, 0.55, titulo, 28, True,
        "branco" if escuro else "navy")
    if subtitulo:
        txt(slide, 0.68, 1.34, 11.90, 0.28, subtitulo, 12, False,
            "branco" if escuro else "texto_fraco")
    regua(slide)


def novo(prs, fundo_tok="off_white"):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    fundo(slide, fundo_tok)
    onda(slide)
    logo(slide)
    return slide


# =====================================================================
# LAYOUTS
# =====================================================================

def l_capa(prs, d):
    slide = novo(prs, "navy")
    barra = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0,
                                   Inches(13.333), Inches(0.12))
    barra.fill.solid()
    barra.fill.fore_color.rgb = _cor("verde")
    barra.line.fill.background()
    barra.shadow.inherit = False

    txt(slide, 0.75, 1.15, 6.50, 0.25, d["eyebrow"].upper(), 11, True, "verde")
    txt(slide, 0.75, 1.55, 7.30, 1.70, d["titulo"], 34, True, "branco",
        entrelinha=1.1)
    txt(slide, 0.75, 3.35, 7.20, 1.10, d["subtitulo"], 17, False,
        "texto_claro2", entrelinha=1.25)
    if d.get("selo"):
        caixa(slide, 0.75, 4.62, 4.30, 0.40, "verde", None, sombra=False)
        txt(slide, 0.75, 4.72, 4.30, 0.24, d["selo"].upper(), 11, True,
            "navy", "centro")
    txt(slide, 0.75, 5.45, 7.00, 1.30, d["autor"], 14, False, "branco",
        entrelinha=1.3)

    caixa(slide, 8.50, 1.10, 3.90, 4.95, "navy_card", "navy_borda")
    for i, item in enumerate(d["agenda"]):
        y = 1.55 + i * 1.50
        txt(slide, 8.85, y, 1.20, 0.50, f"0{i + 1}", 32, True, "verde")
        txt(slide, 8.85, y + 0.58, 3.20, 0.60, item.upper(), 12, True,
            "branco", entrelinha=1.15)
        if i < len(d["agenda"]) - 1:
            regua(slide, 8.85, y + 1.28, 3.20, 0.03)


def l_cards_numerados(prs, d):
    slide = novo(prs, d.get("fundo", "off_white"))
    cabecalho(slide, d["eyebrow"], d["titulo"], d.get("subtitulo", ""))
    cards = d["cards"]
    n = len(cards)
    gap = 0.52
    w = (11.85 - gap * (n - 1)) / n
    y, h = 2.35, 2.65
    for i, c in enumerate(cards):
        x = 0.75 + i * (w + gap)
        caixa(slide, x, y, w, h, "branco", "borda")
        txt(slide, x + 0.28, y + 0.26, 1.20, 0.45, f"0{i + 1}", 24, True,
            "verde")
        txt(slide, x + 0.28, y + 0.82, w - 0.56, 0.50, c["rotulo"].upper(),
            12, True, "navy", entrelinha=1.15)
        txt(slide, x + 0.28, y + 1.42, w - 0.56, h - 1.60, c["texto"], 14,
            False, "texto", entrelinha=1.25)
        if i < n - 1:
            seta(slide, x + w + 0.04, y + h / 2 - 0.28, gap - 0.08)
    if d.get("destaque"):
        caixa(slide, 0.75, 5.55, 11.85, 0.62, "verde_claro", None,
              sombra=False)
        txt(slide, 1.05, 5.74, 2.60, 0.26, d["destaque"]["rotulo"].upper(),
            11, True, "navy")
        txt(slide, 3.55, 5.74, 8.80, 0.26, d["destaque"]["texto"], 13, False,
            "texto")
    if d.get("rodape_txt"):
        rodape(slide, d["rodape_txt"])


def l_definicao_fluxo(prs, d):
    slide = novo(prs, d.get("fundo", "off_white"))
    cabecalho(slide, d["eyebrow"], d["titulo"], d.get("subtitulo", ""))
    de = d["definicao"]
    caixa(slide, 0.75, 2.35, 4.05, 3.85, "navy_card", "navy_borda")
    txt(slide, 1.05, 2.62, 3.45, 0.24, de["rotulo"].upper(), 10, True,
        "verde")
    txt(slide, 1.05, 3.00, 3.45, 1.85, de["frase"], 18, True, "branco",
        entrelinha=1.2)
    txt(slide, 1.05, 5.00, 3.45, 1.05, de["legenda"], 11, False,
        "texto_claro", italico=True, entrelinha=1.25)

    txt(slide, 5.15, 2.32, 6.90, 0.26, de["titulo_direita"].upper(), 12, True,
        "navy")
    for i, etapa in enumerate(d["etapas"]):
        y = 2.72 + i * 0.68
        caixa(slide, 5.15, y, 6.90, 0.48, "verde_claro", None, sombra=False)
        txt(slide, 5.38, y + 0.13, 0.40, 0.26, f"{i + 1}", 12, True,
            "verde_escuro")
        txt(slide, 5.82, y + 0.13, 6.05, 0.26, etapa, 12, False, "texto")
        if i < len(d["etapas"]) - 1:
            regua(slide, 5.55, y + 0.50, 0.02, 0.20)
    if d.get("nota"):
        caixa(slide, 5.15, 5.82, 6.90, 0.52, "off_white", "borda",
              sombra=False)
        txt(slide, 5.40, 6.00, 2.30, 0.24, d["nota"]["rotulo"].upper(), 11,
            True, "navy")
        txt(slide, 7.60, 6.00, 4.20, 0.24, d["nota"]["texto"], 11, False,
            "texto")


def l_lista_processo(prs, d):
    slide = novo(prs, d.get("fundo", "off_white"))
    cabecalho(slide, d["eyebrow"], d["titulo"], d.get("subtitulo", ""))
    li = d["lista"]
    caixa(slide, 0.75, 2.35, 5.90, 2.70, "branco", "borda")
    txt(slide, 1.05, 2.55, 5.30, 0.24, li["rotulo"].upper(), 10, True,
        "verde_escuro")
    for i, item in enumerate(li["itens"]):
        y = 2.92 + i * 0.44
        marcador(slide, 1.05, y + 0.03)
        txt(slide, 1.35, y, 5.00, 0.34, item, 16, True, "navy")
    if li.get("nota"):
        txt(slide, 1.05, 4.72, 5.30, 0.24, li["nota"], 11, False,
            "texto_fraco", italico=True)

    for i, etapa in enumerate(d["etapas"]):
        x = 6.95 + i * 2.30
        escuro = (i == 1)
        caixa(slide, x, 3.05, 1.75, 1.05, "navy" if escuro else "branco",
              None if escuro else "borda")
        txt(slide, x + 0.12, 3.30, 1.51, 0.55, etapa.upper(), 11, True,
            "branco" if escuro else "navy", "centro", entrelinha=1.15)
        if i < len(d["etapas"]) - 1:
            seta(slide, x + 1.79, 3.38, 0.51)
    if d.get("alerta"):
        caixa(slide, 0.75, 5.35, 11.85, 0.62, "verde", None, sombra=False)
        txt(slide, 1.05, 5.54, 2.60, 0.26, d["alerta"]["rotulo"].upper(), 11,
            True, "navy")
        txt(slide, 3.55, 5.54, 8.80, 0.26, d["alerta"]["texto"], 13, False,
            "navy")


def l_definicao_linhas(prs, d):
    slide = novo(prs, d.get("fundo", "off_white"))
    cabecalho(slide, d["eyebrow"], d["titulo"], d.get("subtitulo", ""))
    de = d["definicao"]
    caixa(slide, 0.75, 2.35, 4.05, 3.35, "navy_card", "navy_borda")
    txt(slide, 1.05, 2.60, 3.45, 0.24, de["rotulo"].upper(), 10, True, "verde")
    txt(slide, 1.05, 2.98, 3.45, 1.70, de["frase"], 18, True, "branco",
        entrelinha=1.2)
    txt(slide, 1.05, 4.70, 3.45, 0.90, de["legenda"], 11, False,
        "texto_claro", italico=True, entrelinha=1.25)

    fundos = ["verde_claro", "off_white", "verde"]
    for i, ln in enumerate(d["linhas"]):
        y = 2.45 + i * 1.00
        fill = fundos[i] if i < 3 else "off_white"
        caixa(slide, 5.15, y, 6.75, 0.72, fill,
              "borda" if fill == "off_white" else None, sombra=False)
        txt(slide, 5.45, y + 0.11, 6.15, 0.24, ln["rotulo"].upper(), 13, True,
            "navy")
        txt(slide, 5.45, y + 0.40, 6.15, 0.24, ln["texto"], 11, False,
            "texto" if fill != "verde" else "navy")
    if d.get("faixa"):
        caixa(slide, 0.75, 5.95, 11.85, 0.36, "navy", None, sombra=False)
        txt(slide, 0.75, 6.05, 11.85, 0.22, d["faixa"], 10, True, "branco",
            "centro")


def l_tabela(prs, d):
    slide = novo(prs, d.get("fundo", "branco"))
    cabecalho(slide, d["eyebrow"], d["titulo"], d.get("subtitulo", ""))
    cols = d["colunas"]
    total = sum(c["largura"] for c in cols)
    larguras = [11.85 * c["largura"] / total for c in cols]
    y = 2.35
    x = 0.75
    # Altura de linha adaptativa: o corpo da tabela nunca passa de y 6,45.
    n = len(d["linhas"])
    livre = 6.45 - y - 0.38 - (0.80 if d.get("nota") else 0.0)
    alt = min(0.42, livre / max(n, 1))
    for i, c in enumerate(cols):
        caixa(slide, x, y, larguras[i], 0.38, "navy", None, reto=True,
              sombra=False)
        txt(slide, x + 0.12, y + 0.11, larguras[i] - 0.24, 0.22,
            c["nome"].upper(), 10, True, "branco")
        x += larguras[i]
    for r, linha in enumerate(d["linhas"]):
        yl = y + 0.38 + r * alt
        x = 0.75
        for i, cel in enumerate(linha):
            caixa(slide, x, yl, larguras[i], alt,
                  "zebra" if r % 2 else "branco", "borda", reto=True,
                  sombra=False)
            txt(slide, x + 0.12, yl + alt / 2 - 0.10, larguras[i] - 0.24,
                0.20, cel, 9, False, "texto")
            x += larguras[i]
    fim = y + 0.38 + n * alt
    if d.get("nota"):
        caixa(slide, 0.75, fim + 0.22, 11.85, 0.55, "verde_claro", None,
              sombra=False)
        txt(slide, 1.05, fim + 0.39, 2.60, 0.24, d["nota"]["rotulo"].upper(),
            11, True, "navy")
        txt(slide, 3.55, fim + 0.39, 8.80, 0.24, d["nota"]["texto"], 13,
            False, "texto")
    if d.get("rodape_txt"):
        rodape(slide, d["rodape_txt"])


def l_duas_colunas(prs, d):
    slide = novo(prs, d.get("fundo", "off_white"))
    cabecalho(slide, d["eyebrow"], d["titulo"], d.get("subtitulo", ""))
    for x, col, escuro in ((0.72, d["coluna_clara"], False),
                           (6.78, d["coluna_escura"], True)):
        caixa(slide, x, 2.20, 5.88, 4.25, "navy_card" if escuro else "branco",
              "navy_borda" if escuro else "borda")
        txt(slide, x + 0.32, 2.46, 5.24, 0.24, col["rotulo"].upper(), 10, True,
            "verde" if escuro else "verde_escuro")
        for i, item in enumerate(col["itens"]):
            y = 2.88 + i * 0.86
            txt(slide, x + 0.32, y, 5.24, 0.24, item["titulo"], 12, True,
                "branco" if escuro else "navy")
            txt(slide, x + 0.32, y + 0.28, 5.24, 0.50, item["descricao"], 10,
                False, "texto_claro3" if escuro else "texto", entrelinha=1.2)
    if d.get("rodape_txt"):
        rodape(slide, d["rodape_txt"])


def l_dois_conceitos(prs, d):
    slide = novo(prs, "navy")
    cabecalho(slide, d["eyebrow"], d["titulo"], d.get("subtitulo", ""),
              escuro=True)
    for x, bl, escuro in ((0.75, d["esquerda"], True),
                          (6.90, d["direita"], False)):
        caixa(slide, x, 2.35, 5.65, 3.60, "navy_card" if escuro else "branco",
              "navy_borda" if escuro else None)
        txt(slide, x + 0.32, 2.60, 2.20, 0.50, bl["sigla"], 26, True, "verde")
        txt(slide, x + 0.32 + 2.25, 2.72, 2.80, 0.30, bl["nome"].upper(), 13,
            True, "branco" if escuro else "navy")
        txt(slide, x + 0.32, 3.25, 5.01, 1.00, bl["frase"], 17, True,
            "branco" if escuro else "navy", entrelinha=1.2)
        txt(slide, x + 0.32, 4.45, 5.01, 0.24, bl["rotulo"].upper(), 10, True,
            "verde" if escuro else "verde_escuro")
        txt(slide, x + 0.32, 4.78, 5.01, 1.00, bl["texto"], 11, False,
            "texto_claro" if escuro else "texto", entrelinha=1.25)
    if d.get("conclusao"):
        caixa(slide, 0.75, 6.10, 11.80, 0.44, "verde", None, sombra=False)
        txt(slide, 0.75, 6.23, 11.80, 0.24, d["conclusao"], 14, True, "navy",
            "centro")


def l_codigo(prs, d):
    """Cabecalho + bloco de codigo monoespacado + coluna de leitura."""
    slide = novo(prs, d.get("fundo", "off_white"))
    cabecalho(slide, d["eyebrow"], d["titulo"], d.get("subtitulo", ""))

    caixa(slide, 0.72, 2.15, 7.60, 4.30, "navy_card", "navy_borda")
    txt(slide, 1.02, 2.38, 7.00, 0.24, d["arquivo"], 10, True, "verde")
    bloco_codigo(slide, 1.02, 2.72, 7.00, 3.55, d["codigo"],
                 d.get("tam", 9))

    txt(slide, 8.60, 2.20, 4.00, 0.26, d["rotulo_notas"].upper(), 12, True,
        "navy")
    passo = 0.95 if len(d["notas"]) >= 4 else 1.10
    for i, nota in enumerate(d["notas"]):
        y = 2.62 + i * passo
        marcador(slide, 8.60, y + 0.04, 0.13)
        txt(slide, 8.85, y, 3.75, 0.24, nota["titulo"], 11, True, "navy")
        txt(slide, 8.85, y + 0.28, 3.75, 0.66, nota["texto"], 10, False,
            "texto", entrelinha=1.2)
    if d.get("rodape_txt"):
        rodape(slide, d["rodape_txt"])


def l_divisor(prs, d):
    """Transicao de secao: numero grande + roteiro da parte."""
    slide = novo(prs, "navy")
    barra = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0,
                                   Inches(13.333), Inches(0.12))
    barra.fill.solid()
    barra.fill.fore_color.rgb = _cor("verde")
    barra.line.fill.background()
    barra.shadow.inherit = False

    txt(slide, 0.75, 1.35, 5.50, 0.26, d["eyebrow"].upper(), 11, True, "verde")
    txt(slide, 0.72, 1.70, 3.00, 1.60, d["numero"], 96, True, "verde")
    txt(slide, 0.75, 3.55, 6.20, 1.40, d["titulo"], 32, True, "branco",
        entrelinha=1.1)
    regua(slide, 0.75, 5.15, 4.00, 0.04)
    txt(slide, 0.75, 5.45, 6.00, 0.70, d["subtitulo"], 13, False,
        "texto_claro2", entrelinha=1.3)

    caixa(slide, 7.30, 1.45, 5.30, 4.60, "navy_card", "navy_borda")
    txt(slide, 7.65, 1.75, 4.60, 0.24, d["rotulo"].upper(), 10, True, "verde")
    for i, item in enumerate(d["itens"]):
        y = 2.20 + i * 0.62
        marcador(slide, 7.65, y + 0.05, 0.14)
        txt(slide, 7.95, y, 4.35, 0.50, item, 12, False, "texto_claro3",
            entrelinha=1.2)


LAYOUTS = {
    "capa": l_capa,
    "cards_numerados": l_cards_numerados,
    "definicao_fluxo": l_definicao_fluxo,
    "lista_processo": l_lista_processo,
    "definicao_linhas": l_definicao_linhas,
    "tabela": l_tabela,
    "duas_colunas": l_duas_colunas,
    "dois_conceitos": l_dois_conceitos,
    "codigo": l_codigo,
    "divisor": l_divisor,
}



# =====================================================================
# CONTEUDO
# =====================================================================

CONTEUDO = [
    {"tipo": "capa",
     "eyebrow": "Casa Civil do DF  ·  MongoDB Atlas",
     "titulo": "DODF Search\nArquitetura de um pipeline\nNL2Query deterministico",
     "subtitulo": "Como uma pergunta em portugues vira agregacao MongoDB "
                  "auditavel — e por que o LLM nunca escreve a query.",
     "selo": "Ambiente V2  ·  branch v2",
     "autor": "Marcos Lopes\nSolutions Architect · MongoDB",
     "agenda": ["Ingestao e modelo de dados",
                "Consulta: rotas e indices",
                "Numeros e latencia"]},


    {"tipo": "divisor",
     "eyebrow": "parte 01",
     "numero": "01",
     "titulo": "Fundamentos\ne modelo de dados",
     "subtitulo": "Quem escreve a query, quais colecoes existem e onde cada "
                  "parametro de comportamento e definido.",
     "rotulo": "nesta parte",
     "itens": [
         "T2Q x NL2Q: a decisao que define se a consulta e auditavel",
         "As quatro camadas e o papel de cada modulo Python",
         "Colecoes, indices e a chave de acesso de cada uma",
         "config.py: pool de conexoes e parametros do .env"]},

    {"tipo": "dois_conceitos",
     "eyebrow": "premissa de arquitetura",
     "titulo": "Duas formas de colocar um LLM na frente de um banco",
     "subtitulo": "A escolha define se a consulta e auditavel ou apenas plausivel.",
     "esquerda": {"sigla": "T2Q", "nome": "texto → query",
                  "frase": "O modelo escreve o pipeline e o banco executa o que vier.",
                  "rotulo": "risco assumido",
                  "texto": "MQL alucinada, injecao via prompt, resultado nao "
                           "reproduzivel. Nao ha como auditar de onde veio o numero."},
     "direita": {"sigla": "NL2Q", "nome": "texto → parametro",
                 "frase": "O modelo devolve JSON; o codigo monta a agregacao.",
                 "rotulo": "garantia obtida",
                 "texto": "Chaves fixas, valores validados, pipeline literal em "
                          "Python. Toda consulta e reproduzivel e rastreavel."},
     "conclusao": "O DODF Search implementa o segundo modelo — nl2query.py + _consultar_atos()"},

    {"tipo": "tabela",
     "eyebrow": "mapa do codigo",
     "titulo": "Dez modulos, uma responsabilidade cada",
     "subtitulo": "Nenhum modulo abre conexao por conta propria: todos passam "
                  "por config.py.",
     "fundo": "branco",
     "colunas": [{"nome": "Modulo", "largura": 2.9},
                 {"nome": "Responsabilidade", "largura": 5.6},
                 {"nome": "Acionado por", "largura": 2.5}],
     "linhas": [
         ["config.py", "Pool, GridFS, embedding, rerank, leitura do .env",
          "Todos os modulos"],
         ["processar_pdf.py", "Extracao, limpeza, chunking, embedding, gravacao",
          "CLI e ingestao"],
         ["ocr.py", "OCR de fallback por pagina (gemini | mistral)",
          "processar_pdf.py"],
         ["extrator_atos.py", "Regex de atos, reforco por LLM, normalizacao",
          "processar_pdf.py"],
         ["ingestao_paralela.py", "Pool de processos, 1 PDF por worker, resumivel",
          "CLI"],
         ["reforco_atos.py", "Segunda passada de LLM em chunks residuais", "CLI"],
         ["setup_indices_vetoriais.py", "Cria/atualiza indices vetoriais quantizados",
          "CLI"],
         ["nl2query.py", "Pergunta em portugues -> filtros JSON validados",
          "chatbot.py"],
         ["tools_dodf.py", "Buscas, cache, atos, telemetria, auditoria",
          "chatbot.py"],
         ["chatbot.py", "Streamlit, roteador deterministico, servidor de PDF",
          "Usuario"]],
     "nota": {"rotulo": "regra estrutural",
              "texto": "So config.py abre conexao e so tools_dodf.py monta "
                       "pipeline de agregacao."}},

    {"tipo": "cards_numerados",
     "eyebrow": "visao geral",
     "titulo": "Quatro camadas, um unico banco de dados",
     "subtitulo": "Vetor, texto, estruturado, cache e o PDF original no mesmo cluster.",
     "cards": [
         {"rotulo": "Apresentacao",
          "texto": "Streamlit com tema co-branded. Um servidor HTTP na porta "
                   "8502 entrega o PDF do GridFS na pagina citada."},
         {"rotulo": "Aplicacao",
          "texto": "chatbot.py — roteador deterministico: cumprimento, cache, "
                   "rota analitica, rota semantica."},
         {"rotulo": "Inteligencia",
          "texto": "voyage-4-large (1024 d) no embedding, rerank-2.5 na "
                   "relevancia, Claude ou Gemini na redacao."},
         {"rotulo": "Dados",
          "texto": "MongoDB Atlas: Search, Vector Search, agregacao analitica "
                   "e GridFS na mesma plataforma."}],
     "destaque": {"rotulo": "consequencia",
                  "texto": "Sem ETL entre sistemas: a mesma query pode filtrar por "
                           "metadado, buscar por vetor e citar o arquivo de origem."}},

    {"tipo": "tabela",
     "eyebrow": "modelo de dados",
     "titulo": "Colecoes e indices",
     "subtitulo": "Cada colecao tem um papel unico e um caminho de acesso definido.",
     "colunas": [{"nome": "Colecao", "largura": 2.0},
                 {"nome": "Papel", "largura": 3.4},
                 {"nome": "Indice", "largura": 3.2},
                 {"nome": "Chave de acesso", "largura": 3.3}],
     "linhas": [
         ["documentos", "Chunks de texto (1.500 chars, overlap 300)",
          "busca_textual + busca_vetorial", "texto, texto.fonetico, embedding"],
         ["atos", "Atos de pessoal estruturados", "B-tree",
          "nome_normalizado, tipo_ato, ano, orgao"],
         ["pdfs", "Metadados da edicao", "B-tree", "arquivo, total_paginas"],
         ["fs.files / fs.chunks", "PDF original (GridFS)", "B-tree", "filename"],
         ["cache_semantico", "Perguntas ja respondidas", "cache_vetorial",
          "pergunta_embedding"],
         ["metricas", "Telemetria por ferramenta", "B-tree",
          "timestamp, ferramenta"]],
     "nota": {"rotulo": "quantizacao",
              "texto": "VECTOR_QUANTIZATION=scalar — mesmo recall com fracao da "
                       "memoria do indice vetorial."},
     "rodape_txt": "Nomes de indice e de campo vem de config.py / .env: "
                   "VECTOR_INDEX_NAME, VECTOR_FIELD, CACHE_INDEX_NAME."},

    {"tipo": "codigo",
     "eyebrow": "fundamentos · conexao",
     "titulo": "Um unico MongoClient para todo o processo",
     "subtitulo": "O Streamlit reexecuta o script a cada interacao — o pool "
                  "precisa sobreviver ao rerun.",
     "arquivo": "config.py · get_client()",
     "codigo": """# singleton: o pool e criado uma vez por processo
_client = None

def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(
            CFG.MONGODB_URI,
            maxPoolSize=CFG.MONGO_MAX_POOL_SIZE,      # 100
            minPoolSize=CFG.MONGO_MIN_POOL_SIZE,      # 5
            serverSelectionTimeoutMS=5000,
            retryWrites=True,
            retryReads=True,
            appname="dodf-search",
        )
    return _client

def get_db():     return get_client()[CFG.MONGODB_DB]
def get_gridfs(): return GridFS(get_db())""",
     "rotulo_notas": "por que importa",
     "notas": [
         {"titulo": "Rerun do Streamlit",
          "texto": "Sem singleton, cada interacao abriria um pool novo e o "
                   "handshake TLS dominaria a latencia."},
         {"titulo": "minPoolSize = 5",
          "texto": "Conexoes quentes desde o primeiro clique — a busca paralela "
                   "sempre encontra socket livre."},
         {"titulo": "retryWrites / retryReads",
          "texto": "Failover de replica set e absorvido pelo driver, sem "
                   "tratamento na aplicacao."},
         {"titulo": "appname",
          "texto": "Toda operacao aparece identificada no profiler do Atlas."}]},

    {"tipo": "tabela",
     "eyebrow": "fundamentos · configuracao",
     "titulo": "Os parametros que mudam o comportamento",
     "subtitulo": "Lidos uma unica vez em config._Config; nenhum valor esta "
                  "espalhado pelo codigo.",
     "colunas": [{"nome": "Variavel", "largura": 3.7},
                 {"nome": "Valor", "largura": 1.5},
                 {"nome": "Efeito", "largura": 6.8}],
     "linhas": [
         ["CHUNK_SIZE / CHUNK_OVERLAP", "1500 / 300",
          "Tamanho do trecho e continuidade entre chunks vizinhos"],
         ["VOYAGE_EMBEDDING_MODEL", "voyage-4-large",
          "Modelo de embedding — 1024 dimensoes por vetor"],
         ["VOYAGE_EMBEDDING_BATCH", "128", "Chunks por chamada de API na ingestao"],
         ["VECTOR_QUANTIZATION", "scalar",
          "Memoria do indice vetorial (~3,75x menor que fidelidade plena)"],
         ["VECTOR_NUM_CANDIDATES", "150",
          "Candidatos ANN antes do corte — recall x latencia"],
         ["RANKFUSION_ENABLED / PESO_TEXTUAL / PESO_SEMANTICO", "true / 1 / 1",
          "Fusao hibrida no Atlas ($rankFusion) e peso de cada ramo no RRF"],
         ["CACHE_SIMILARITY", "0.97",
          "Limiar para considerar duas perguntas equivalentes"],
         ["RERANK_TOP_K", "6", "Trechos entregues ao LLM redator"],
         ["RERANK_SKIP_SCORE", "0",
          "Acima de 0, pula o rerank quando ha vencedor claro"],
         ["OCR_MIN_CHARS / OCR_MAX_PAGES", "120 / 50",
          "Quando o OCR e acionado e teto de custo por edicao"],
         ["INGEST_WORKERS / ATOS_REFORCO_WORKERS", "4 / 4",
          "Paralelismo da ingestao e do reforco de atos"]],
     "nota": {"rotulo": "consequencia",
              "texto": "Ajustar recall, custo ou latencia e editar .env — nao ha "
                       "deploy de codigo envolvido."}},

    {"tipo": "divisor",
     "eyebrow": "parte 02",
     "numero": "02",
     "titulo": "Ingestao:\ndo PDF ao dado consultavel",
     "subtitulo": "O caminho entre o arquivo publicado e um chunk vetorizado "
                  "com ato estruturado e pagina citavel.",
     "rotulo": "nesta parte",
     "itens": [
         "Deduplicacao por hash e o PDF original no GridFS",
         "Limpeza, OCR condicional e criterio de qualidade",
         "Chunking com separadores juridicos e overlap verificado",
         "Extracao de atos: regex primeiro, LLM como excecao",
         "Paralelismo por processo e indices quantizados"]},


    {"tipo": "lista_processo",
     "eyebrow": "ciclo 1 · ingestao",
     "titulo": "Do PDF publicado ao dado consultavel",
     "subtitulo": "O dado nasce estruturado, nao apenas vetorizado.",
     "lista": {"rotulo": "o que entra na base",
               "itens": ["PDF da edicao publicada", "Texto pagina por pagina",
                         "Chunks vetorizados", "Atos de pessoal estruturados"],
               "nota": "CHUNK_SIZE=1500 · CHUNK_OVERLAP=300 · lote de embedding = 128"},
     "etapas": ["Extracao\n+ OCR", "Chunk\n+ Embedding", "Gravacao\natomica"],
     "alerta": {"rotulo": "paralelismo (V2)",
                "texto": "Paginas processadas em paralelo e embeddings em lote: o "
                         "gargalo passou a ser a API, nao o cluster."}},

    {"tipo": "codigo",
     "eyebrow": "ciclo 1 · orquestracao",
     "titulo": "A ingestao e uma maquina de estados no proprio banco",
     "subtitulo": "processar_pdf_bytes() — o estado de cada edicao vive na "
                  "colecao pdfs, nunca em memoria.",
     "arquivo": "processar_pdf.py · processar_pdf_bytes()",
     "codigo": """hash_md5 = _hash_bytes(data)             # md5 do arquivo
if _ja_processado(hash_md5):
    return {"status": "ja_processado"}   # dedupe: sai sem custo

col_pdfs.update_one({"hash_md5": hash_md5},
    {"$set": {"status": "processando", ...}}, upsert=True)
try:
    gridfs_id = _salvar_no_gridfs(nome, data, hash_md5)
    paginas, total = _extrair_texto(data)     # PyMuPDF (+ OCR)
    chunks = _criar_chunks(paginas, nome, total)
    _gerar_embeddings_e_salvar(chunks, hash_md5, pdf_id=pdf_id)
    n_atos = _extrair_e_salvar_atos(chunks, hash_md5)
    _registrar_pdf(...)                       # status: processado
except Exception as e:
    col_pdfs.update_one({"hash_md5": hash_md5},
        {"$set": {"status": "erro", "erro": str(e)}})""",
     "rotulo_notas": "propriedades",
     "notas": [
         {"titulo": "Idempotente",
          "texto": "Reprocessar a mesma edicao nao duplica chunk nem ato: o "
                   "hash barra na primeira linha."},
         {"titulo": "Resumivel",
          "texto": "processando / processado / erro ficam no banco — a ingestao "
                   "pode ser retomada a qualquer momento."},
         {"titulo": "Erro isolado",
          "texto": "A falha e gravada no registro daquela edicao; as demais "
                   "seguem processando."},
         {"titulo": "Ordem obrigatoria",
          "texto": "GridFS primeiro: sem o binario salvo nao ha como citar a "
                   "pagina na resposta."}],
     "fundo": "branco"},

    {"tipo": "definicao_fluxo",
     "eyebrow": "ciclo 1 · identidade e origem",
     "titulo": "Por que o hash MD5 e o PDF dentro do GridFS",
     "subtitulo": "A mesma edicao chega por upload web, pasta local ou "
                  "reprocessamento — e sempre o mesmo documento.",
     "definicao": {"rotulo": "identidade do documento",
                   "frase": "O nome do arquivo nao identifica a edicao. O conteudo identifica.",
                   "legenda": "hash_arquivo liga chunk, ato e PDF: excluir uma "
                              "edicao e um delete_many por hash.",
                   "titulo_direita": "o que o hash garante"},
     "etapas": [
         "Deduplicacao: _ja_processado() consulta pdfs por hash_md5 + status",
         "Rastreabilidade: todo chunk e todo ato carregam hash_arquivo",
         "Exclusao completa: chunks, atos, registro e binario saem juntos",
         "Citacao verificavel: o servidor 8502 entrega o PDF na pagina citada"],
     "nota": {"rotulo": "no gridfs",
              "texto": "filename + md5_hash evitam gravar o binario duas vezes."}},


    {"tipo": "codigo",
     "eyebrow": "ciclo 1 · extracao",
     "titulo": "A pagina so vai ao OCR se a extracao nativa falhar",
     "subtitulo": "_extrair_texto() decide pagina por pagina com base em "
                  "qualidade medida, nao em suposicao.",
     "arquivo": "processar_pdf.py · _extrair_texto()",
     "codigo": """texto_bruto = doc[num].get_text("text", sort=True)
texto_limpo = _limpar_texto(texto_bruto)      # 20+ regex de limpeza
qualidade = _calcular_qualidade(texto_limpo)  # palavras, ratio_alfa

precisa_ocr = (not qualidade.get("aprovado")
               or len(texto_limpo) < CFG.OCR_MIN_CHARS)    # 120
if (precisa_ocr and CFG.OCR_ENABLED
        and ocr_usadas < CFG.OCR_MAX_PAGES_POR_PDF):       # teto 50
    texto_ocr = _ocr_fallback_pagina(doc[num])   # render 200 dpi
    if texto_ocr:
        ocr_usadas += 1
        q_ocr = _calcular_qualidade(texto_ocr)
        if q_ocr["aprovado"] and len(texto_ocr) > len(texto_limpo):
            texto_limpo, qualidade = texto_ocr, q_ocr

if texto_limpo and qualidade.get("aprovado"):
    paginas.append({"pagina": num + 1, "texto": texto_limpo,
                    "qualidade": qualidade})""",
     "rotulo_notas": "leitura",
     "notas": [
         {"titulo": "sort=True",
          "texto": "PyMuPDF devolve o texto na ordem de leitura das colunas do "
                   "Diario, nao na ordem interna do arquivo."},
         {"titulo": "Qualidade medida",
          "texto": "palavras, proporcao de caracteres alfabeticos e linhas "
                   "uteis decidem se a pagina entra na base."},
         {"titulo": "OCR nunca piora",
          "texto": "O texto do OCR so substitui o nativo se for aprovado e mais "
                   "completo."},
         {"titulo": "Provedor plugavel",
          "texto": "ocr.py expoe gemini e mistral atras da mesma funcao e "
                   "devolve '' em qualquer falha."}]},

    {"tipo": "definicao_linhas",
     "eyebrow": "ciclo 1 · decisoes",
     "titulo": "Onde a ingestao decide gastar uma chamada de API",
     "subtitulo": "Todo caminho caro e protegido por um limiar numerico.",
     "definicao": {"rotulo": "gate deterministico",
                   "frase": "Nenhum modelo e chamado sem que um contador de caracteres autorize.",
                   "legenda": "OCR_MIN_CHARS=120 · OCR_MAX_PAGES_POR_PDF=50 — "
                              "o custo por edicao e previsivel."},
     "linhas": [
         {"rotulo": "1 · Extracao nativa",
          "texto": "PyMuPDF le o texto embutido no PDF. Custo zero, nenhuma chamada externa."},
         {"rotulo": "2 · OCR condicional",
          "texto": "So a pagina com menos de 120 caracteres vai para o OCR (OCR_PROVIDER=gemini)."},
         {"rotulo": "3 · Regex primeiro, LLM depois",
          "texto": "O parser regex extrai o ato; o reforco por LLM roda apenas nos chunks residuais."}],
     "faixa": "O LLM entra como excecao na ingestao — nunca como caminho padrao."},

    {"tipo": "codigo",
     "eyebrow": "ciclo 1 · chunking",
     "titulo": "Separadores juridicos preservam a unidade do ato",
     "subtitulo": "_criar_chunks() corta respeitando a estrutura do Diario e "
                  "mantem o mapeamento de pagina.",
     "arquivo": "processar_pdf.py · _criar_chunks()",
     "codigo": """# do mais especifico ao mais generico
SEPARADORES_JURIDICOS = [
    "\\n\\n",
    "\\nArt.", "\\nEDITAL", "\\nPORTARIA", "\\nDECRETO",
    "\\nRESOLUCAO", "\\nDESPACHO",
    "\\n", ". ", "; ", " ",
]

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CFG.CHUNK_SIZE,          # 1500
    chunk_overlap=CFG.CHUNK_OVERLAP,    # 300
    separators=SEPARADORES_JURIDICOS,
    keep_separator=False)

# interseccao com o mapa (inicio, fim, pagina) do texto concatenado
for ini, fim, pag in mapa_paginas:
    if pos_inicio < fim and pos_fim > ini:
        pags_chunk.append(pag)""",
     "rotulo_notas": "efeitos",
     "notas": [
         {"titulo": "Corte na fronteira certa",
          "texto": "O splitter tenta quebrar em Art., PORTARIA ou DECRETO antes "
                   "de recorrer a espaco."},
         {"titulo": "Overlap verificado",
          "texto": "O codigo confere se o fim do chunk anterior reaparece no "
                   "seguinte e grava overlap_chars."},
         {"titulo": "Pagina por interseccao",
          "texto": "Chunk que atravessa paginas registra paginas_grupo e cita a "
                   "primeira."},
         {"titulo": "Descarte final",
          "texto": "Trecho sem qualidade ou com menos de 50 caracteres nao "
                   "entra na base."}],
     "fundo": "branco"},

    {"tipo": "tabela",
     "eyebrow": "modelo de dados",
     "titulo": "Anatomia de um documento da colecao documentos",
     "subtitulo": "Um chunk carrega o texto, o vetor e tudo que a citacao exige.",
     "colunas": [{"nome": "Campo", "largura": 3.4},
                 {"nome": "Conteudo", "largura": 5.2},
                 {"nome": "Para que serve", "largura": 3.4}],
     "linhas": [
         ["texto", "Trecho limpo — 1.110 chars em media",
          "Atlas Search e contexto do LLM"],
         ["embedding", "1024 floats de voyage-4-large", "$vectorSearch"],
         ["hash_arquivo", "MD5 da edicao de origem",
          "Dedupe, exclusao, reprocesso"],
         ["pdf_id", "ObjectId do registro em pdfs", "Ligacao com a edicao"],
         ["metadados.arquivo / pagina", "DODF 015 22-01-2025 INTEGRA.pdf / 37",
          "Citacao (Fonte: arquivo, p. N)"],
         ["metadados.paginas_grupo", "Paginas cobertas pelo chunk",
          "Trecho que atravessa pagina"],
         ["metadados.chunk_numero", "Ordem dentro da edicao",
          "Reconstruir a sequencia"],
         ["metadados.tamanho_chars / palavras", "Metricas do trecho",
          "Diagnostico de qualidade"],
         ["metadados.overlap_chars", "Sobreposicao com o chunk anterior",
          "Verificacao de continuidade"],
         ["metadados.embedding_modelo / dimensao", "voyage-4-large / 1024",
          "Auditoria de reindexacao"]],
     "nota": {"rotulo": "por que gravar o modelo",
              "texto": "Trocar de modelo de embedding exige reindexar — o campo "
                       "diz exatamente o que precisa ser refeito."},
     "rodape_txt": "texto.fonetico e texto.normalizado sao analisadores do indice "
                   "busca_textual, nao campos gravados no documento."},

    {"tipo": "codigo",
     "eyebrow": "ciclo 1 · embeddings",
     "titulo": "Lotes de 128, retry crescente, gravacao incremental",
     "subtitulo": "A API de embedding e o gargalo da ingestao — cada lote e "
                  "protegido e persistido ao concluir.",
     "arquivo": "processar_pdf.py · _gerar_embeddings_e_salvar()",
     "codigo": """LOTE = CFG.VOYAGE_EMBEDDING_BATCH   # 128
MAX_RETRIES = 3

for i in range(0, total, LOTE):
    lote = chunks[i:i + LOTE]
    textos = [c["texto"] for c in lote]

    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            vetores = modelo.embed_documents(textos)
            break
        except Exception:
            if tentativa < MAX_RETRIES:
                time.sleep(tentativa * 5)    # 5s, depois 10s
            else:
                raise

    col.insert_many([{"texto": c["texto"],
                      "embedding": vetores[j],
                      "metadados": c["metadados"],
                      "hash_arquivo": hash_md5} ...])""",
     "rotulo_notas": "decisoes",
     "notas": [
         {"titulo": "128 por chamada",
          "texto": "51.714 chunks viram cerca de 404 chamadas de API em vez de "
                   "51.714."},
         {"titulo": "Espera crescente",
          "texto": "Rate limit e instabilidade momentanea nao derrubam a "
                   "ingestao da edicao."},
         {"titulo": "insert_many por lote",
          "texto": "O progresso e persistido a cada 128 chunks; nada e perdido "
                   "se o processo cair."},
         {"titulo": "input_type",
          "texto": "document na ingestao, query na consulta — a Voyage usa "
                   "prefixos distintos para cada caso."}]},

    {"tipo": "definicao_linhas",
     "eyebrow": "ciclo 1 · atos",
     "titulo": "Regex primeiro, LLM so no que sobrou",
     "subtitulo": "extrator_atos.extrair_atos() — a chamada de API depende de "
                  "duas condicoes simultaneas.",
     "definicao": {"rotulo": "estrategia hibrida",
                   "frase": "O LLM nao le a base inteira: le apenas o que o regex nao entendeu.",
                   "legenda": "Custo proporcional a excecao, nao ao volume de "
                              "texto ingerido."},
     "linhas": [
         {"rotulo": "1 · regex extrai",
          "texto": "extrair_regex() percorre dois padroes e devolve nome, tipo, cargo e orgao."},
         {"rotulo": "2 · gatilho verifica",
          "texto": "_TRIGGER busca NOMEAR|EXONERAR|DESIGNAR|DISPENSAR e as formas nomead/exonerad."},
         {"rotulo": "3 · llm reforca",
          "texto": "Sem ato E com gatilho E ATOS_LLM_ENABLED: Claude le os primeiros 4.000 chars."}],
     "faixa": "Falha na API do LLM retorna [] — a ingestao segue com o que o regex extraiu."},

    {"tipo": "codigo",
     "eyebrow": "ciclo 1 · atos",
     "titulo": "Os dois padroes que reconhecem um ato de pessoal",
     "subtitulo": "Nome em maiusculas e delimitador obrigatorio — o regex nao "
                  "adivinha onde o nome termina.",
     "arquivo": "extrator_atos.py · _RE_ATOS e extrair_atos()",
     "codigo": """_TRIGGER = re.compile(r"NOMEAR|EXONERAR|DESIGNAR|DISPENSAR"
                      r"|nomead|exonerad|designad|dispensad", re.IGNORECASE)

_RE_ATOS = [
    # verbo no imperativo + NOME EM MAIUSCULAS + delimitador
    r"(NOMEAR|EXONERAR|DESIGNAR|DISPENSAR)\\s*,?\\s*(?:a\\s+pedido\\s*,?\\s*)?"
    r"([A-Z][A-Z\\s]{6,60}?)(?:\\s*,|\\s+para|\\s+do\\s+Cargo|\\s+matricula)",
    # forma participial: "fica nomeada MARIA DA SILVA, para..."
    r"(nomead[oa]|exonerad[oa]|designad[oa]|dispensad[oa])\\s*,?\\s*"
    r"([A-Z][A-Z\\s]{6,60}?)(?:\\s*,|\\s+para|\\s+do\\s+Cargo)",
]

def extrair_atos(texto, arquivo, pagina, hash_arq) -> list:
    atos = extrair_regex(texto, arquivo, pagina, hash_arq)
    if (not atos and _TRIGGER.search(texto)         # tem gatilho
            and CFG.ATOS_LLM_ENABLED and CFG.ANTHROPIC_API_KEY):
        atos = extrair_llm(texto, arquivo, pagina, hash_arq)   # Claude
    return atos""",
     "rotulo_notas": "detalhes",
     "notas": [
         {"titulo": "Delimitador a direita",
          "texto": "virgula, 'para', 'do Cargo' ou 'matricula' fecham o nome — "
                   "evitam capturar a frase inteira."},
         {"titulo": "Filtro de ruido",
          "texto": "Nome com 6 caracteres ou menos, ou sem espaco, e descartado "
                   "antes de virar ato."},
         {"titulo": "Cargo e orgao",
          "texto": "_RE_CARGO e _RE_ORGAO leem o contexto ao redor do match; "
                   "ausencia vira string vazia."},
         {"titulo": "Fonte preservada",
          "texto": "O trecho de contexto e gravado no ato para conferencia "
                   "manual posterior."}],
     "fundo": "branco"},

    {"tipo": "tabela",
     "eyebrow": "modelo de dados",
     "titulo": "Anatomia de um documento da colecao atos",
     "subtitulo": "Aqui o texto ja virou dado: e esta colecao que responde "
                  "'quantos' e 'quais'.",
     "colunas": [{"nome": "Campo", "largura": 3.2},
                 {"nome": "Conteudo", "largura": 5.4},
                 {"nome": "Para que serve", "largura": 3.4}],
     "linhas": [
         ["nome", "MARIA DA SILVA -> Maria Da Silva (title case)",
          "Exibicao na resposta"],
         ["nome_normalizado", "maria da silva — minusculas, sem acento",
          "Filtro por palavra inteira"],
         ["tipo_ato", "nomeacao | exoneracao | designacao | dispensacao",
          "$match e $group"],
         ["cargo / orgao", "Capturados por regex de contexto",
          "Filtros opcionais"],
         ["data / ano / mes", "Derivados do nome do arquivo (22-01-2025)",
          "Recorte temporal"],
         ["arquivo / pagina", "Edicao e pagina exata do ato",
          "Citacao verificavel"],
         ["hash_arquivo", "MD5 da edicao de origem",
          "Reprocesso e exclusao"],
         ["fonte", "Trecho de contexto ao redor do ato",
          "Conferencia manual"],
         ["metodo_extracao", "regex | llm", "Auditoria de qualidade"],
         ["criado_em", "Timestamp da gravacao", "Diagnostico de carga"]],
     "nota": {"rotulo": "idempotencia",
              "texto": "delete_many por hash_arquivo antes do insert_many; "
                       "dedupe por (nome_normalizado, tipo_ato, pagina)."}},

    {"tipo": "codigo",
     "eyebrow": "ciclo 1 · paralelismo",
     "titulo": "Um processo por PDF, retomada sem controle externo",
     "subtitulo": "ingestao_paralela.py — a deduplicacao por hash e o que torna "
                  "o pool resumivel.",
     "arquivo": "ingestao_paralela.py · ingerir_pasta() e _worker()",
     "codigo": """with ProcessPoolExecutor(max_workers=workers) as pool:  # INGEST_WORKERS
    futuros = {pool.submit(_worker, p, origem, forcar): p for p in pdfs}
    try:
        for fut in as_completed(futuros):
            r = fut.result()
            if r["status"] == "processado":      ok += 1
            elif r["status"] == "ja_processado": pulados += 1
            else:                               erros += 1
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        raise                     # reexecutar retoma de onde parou

def _worker(caminho, origem, forcar) -> dict:
    try:
        data = open(caminho, "rb").read()
        return processar_pdf_bytes(os.path.basename(caminho), data, origem)
    except Exception as e:        # 1 arquivo ruim nao derruba a fila
        return {"status": "erro", "erro": str(e)[:200]}""",
     "rotulo_notas": "por que processo",
     "notas": [
         {"titulo": "Processo, nao thread",
          "texto": "PyMuPDF e o parsing sao CPU-bound: o GIL tornaria threads "
                   "inuteis nessa etapa."},
         {"titulo": "Estado no banco",
          "texto": "Nao existe arquivo de checkpoint — a colecao pdfs e a unica "
                   "fonte de progresso."},
         {"titulo": "Ctrl+C seguro",
          "texto": "cancel_futures descarta o que nao comecou; o que estava em "
                   "andamento fica marcado e sera refeito."},
         {"titulo": "--forcar",
          "texto": "Apaga chunks e registro daquele hash antes de reprocessar "
                   "in-place."}]},

    {"tipo": "cards_numerados",
     "eyebrow": "ciclo 1 · indices",
     "titulo": "Quantizacao escalar: memoria menor, recall preservado",
     "subtitulo": "setup_indices_vetoriais.py — idempotente por definicao, "
                  "comparando o que ja existe no Atlas.",
     "cards": [
         {"rotulo": "Definicao com quantization",
          "texto": "type vector, path embedding, numDimensions 1024, similarity "
                   "cosine e quantization: scalar."},
         {"rotulo": "Comparacao antes de agir",
          "texto": "_quant_atual() le latestDefinition: se a quantizacao ja "
                   "coincide, o script nao faz nada."},
         {"rotulo": "Rebuild em background",
          "texto": "update_search_index() dispara a reconstrucao; aguardar_pronto() "
                   "espera READY com timeout de 600s."}],
     "destaque": {"rotulo": "efeito",
                  "texto": "scalar reduz ~3,75x a memoria por vetor (binary ~24x) "
                           "e o Atlas rescoreia em fidelidade plena."},
     "rodape_txt": "Gerencia os dois indices vetoriais: busca_vetorial "
                   "(documentos) e cache_vetorial (cache_semantico)."},

    {"tipo": "divisor",
     "eyebrow": "parte 03",
     "numero": "03",
     "titulo": "Consulta:\nda pergunta a resposta citada",
     "subtitulo": "Quatro rotas, do custo zero a busca hibrida completa — e a "
                  "regra que escolhe entre elas.",
     "rotulo": "nesta parte",
     "itens": [
         "Roteador deterministico e cache semantico",
         "Rota analitica: LLM propoe, Python constroi a MQL",
         "Rota semantica: $search e $vectorSearch em paralelo",
         "Rerank condicional e o prompt do redator",
         "Telemetria, latencia por rota e citacao verificavel"]},



    {"tipo": "definicao_fluxo",
     "eyebrow": "ciclo 2 · roteamento",
     "titulo": "A rota e escolhida antes de qualquer modelo ser consultado",
     "subtitulo": "chatbot.py · pipeline_rapido() — ordem fixa, do mais barato ao mais caro.",
     "definicao": {"rotulo": "roteador deterministico",
                   "frase": "Substring e limiar decidem o caminho. O LLM nao participa.",
                   "legenda": "A decisao e legivel, testavel e identica em toda execucao.",
                   "titulo_direita": "ordem de avaliacao"},
     "etapas": [
         "Cumprimento — resposta canned, zero chamada externa",
         "Cache semantico — $vectorSearch em cache_semantico, similaridade >= 0,97",
         "Gatilho de ato — substring nomea / exoner / design / dispens abre a rota analitica",
         "Fallback semantico — busca hibrida com limite = 6 chunks"],
     "nota": {"rotulo": "economia",
              "texto": "Sem gatilho, o nl2query nem e chamado."}},

    {"tipo": "codigo",
     "eyebrow": "ciclo 2 · cache",
     "titulo": "O cache compara significado, nao texto",
     "subtitulo": "verificar_cache() — 'quantos foram nomeados?' e 'total de "
                  "nomeacoes?' sao a mesma pergunta.",
     "arquivo": "tools_dodf.py · verificar_cache() e salvar_cache()",
     "codigo": """r = list(db["cache_semantico"].aggregate([
    {"$vectorSearch": {"index": CFG.CACHE_INDEX_NAME,     # cache_vetorial
                       "path": CFG.CACHE_VECTOR_FIELD,
                       "queryVector": vetor,
                       "numCandidates": CFG.CACHE_NUM_CANDIDATES,
                       "limit": 1}},
    {"$project": {"resposta": 1,
                  "score": {"$meta": "vectorSearchScore"}}}
]))
if r and r[0].get("score", 0) >= limiar:      # CACHE_SIMILARITY = 0.97
    return r[0]["resposta"]
return None                                   # segue o pipeline

# ao final da resposta, o par pergunta/resposta e guardado com TTL
db["cache_semantico"].insert_one({
    "pergunta": pergunta, CFG.CACHE_VECTOR_FIELD: vetor,
    "resposta": resposta, "criado_em": datetime.now(),
    "ttl": datetime.now() + timedelta(days=7)})""",
     "rotulo_notas": "decisoes",
     "notas": [
         {"titulo": "limit 1",
          "texto": "So o vizinho mais proximo interessa: o limiar decide se ele "
                   "vale como resposta."},
         {"titulo": "0,97 e conservador",
          "texto": "Limiar baixo devolveria a resposta de outra pergunta; alto "
                   "demais anularia o cache."},
         {"titulo": "TTL de 7 dias",
          "texto": "Indice TTL do MongoDB expira a entrada — a base muda e a "
                   "resposta envelhece."},
         {"titulo": "Vetor reaproveitado",
          "texto": "O mesmo embedding da pergunta serve ao cache e a busca "
                   "semantica: uma unica chamada."}],
     "fundo": "branco"},


    {"tipo": "duas_colunas",
     "eyebrow": "ciclo 2 · rota analitica",
     "titulo": "Como a MQL nasce: o LLM propoe, o Python constroi",
     "subtitulo": "nl2query.interpretar() → _normalizar() → tools_dodf._consultar_atos()",
     "coluna_clara": {
         "rotulo": "o llm devolve",
         "itens": [
             {"titulo": "JSON de chaves fixas",
              "descricao": "analitica, operacao, nome_pessoa, tipo_ato, cargo, "
                           "orgao, ano, mes. Nada alem disso e aceito."},
             {"titulo": "Nenhum operador MongoDB",
              "descricao": "O prompt proibe texto extra; a saida e parseada como "
                           "JSON ou inteiramente descartada."},
             {"titulo": "Exemplo real",
              "descricao": "'quantos pedros nomeados em 2025' → "
                           "{nome_pessoa: 'pedro', tipo_ato: 'nomeacao', ano: '2025'}"},
             {"titulo": "Se a API falhar",
              "descricao": "interpretar() retorna None e o fluxo cai no fallback "
                           "por regex, sem perder a rota."}]},
     "coluna_escura": {
         "rotulo": "o python constroi",
         "itens": [
             {"titulo": "$match campo a campo",
              "descricao": "Somente as chaves preenchidas entram no filtro; "
                           "re.escape() no termo vindo do usuario."},
             {"titulo": "Limite de palavra inteira",
              "descricao": "\\bpedro\\b casa 'Pedro Silva' e 'Joao Pedro', "
                           "mas nunca 'Pedroso'."},
             {"titulo": "$group e $sort literais",
              "descricao": "A agregacao e imutavel no codigo; so a variavel "
                           "filtro muda entre execucoes."},
             {"titulo": "Indices B-tree",
              "descricao": "nome_normalizado, tipo_ato, ano, orgao. Esta rota "
                           "nao usa Atlas Search."}]},
     "rodape_txt": "tools_dodf.py · _consultar_atos() — a contagem e um $group do MongoDB."},

    {"tipo": "definicao_linhas",
     "eyebrow": "ciclo 2 · sanitizacao",
     "titulo": "A fronteira de confianca com o modelo",
     "subtitulo": "nl2query._normalizar() — o unico ponto onde a saida do LLM e aceita.",
     "fundo": "branco",
     "definicao": {"rotulo": "principio",
                   "frase": "Nada que o modelo diz entra na query sem passar por validacao.",
                   "legenda": "Cada campo tem um tipo, um dominio e um "
                              "comportamento definido para valor invalido."},
     "linhas": [
         {"rotulo": "tipo_ato",
          "texto": "Passa por tipo_canonico(); valor fora do vocabulario conhecido e descartado."},
         {"rotulo": "ano e mes",
          "texto": "ano so com 4 digitos; mes so entre 1 e 12. Fora disso, string vazia."},
         {"rotulo": "nome_pessoa",
          "texto": "normalizar() + re.escape() antes de virar regex — injecao de padrao e impossivel."}],
     "faixa": "Filtro vazio nao vira consulta ampla: sem chave valida, a rota analitica e abandonada."},

    {"tipo": "cards_numerados",
     "eyebrow": "ciclo 2 · resiliencia",
     "titulo": "A rota analitica sobrevive a queda do LLM",
     "subtitulo": "Tres mecanismos independentes garantem a contagem exata.",
     "cards": [
         {"rotulo": "Gatilho por substring",
          "texto": "_GATILHO_TIPO em chatbot.py. Quatro raizes cobrem os atos de "
                   "pessoal sem custo de API."},
         {"rotulo": "Fallback sem LLM",
          "texto": "_filtros_atos() extrai tipo, ano e mes por regex puro quando "
                   "a interpretacao falha."},
         {"rotulo": "Contagem no banco",
          "texto": "O numero vem de um $group sobre a colecao atos — nunca de "
                   "uma estimativa do modelo."}],
     "destaque": {"rotulo": "consequencia",
                  "texto": "Com a API de LLM indisponivel, o sistema continua "
                           "respondendo perguntas de contagem e listagem."}},

    {"tipo": "dois_conceitos",
     "eyebrow": "ciclo 2 · rota semantica",
     "titulo": "Os dois indices nao competem: rodam juntos",
     "subtitulo": "tools_dodf.busca_rapida_paralela() — um unico $rankFusion com dois "
                  "sub-pipelines ($search e $vectorSearch).",
     "esquerda": {"sigla": "$search", "nome": "indice textual",
                  "frase": "Nome proprio, numero de decreto, grafia com erro.",
                  "rotulo": "busca_textual · string literal no pipeline",
                  "texto": "compound.should em quatro caminhos: texto, "
                           "texto.fonetico, texto.normalizado e phrase. "
                           "Fuzzy com maxEdits=2."},
     "direita": {"sigla": "$vectorSearch", "nome": "indice vetorial",
                 "frase": "Intencao, sinonimo, pergunta indireta.",
                 "rotulo": "CFG.VECTOR_INDEX_NAME · vem do .env",
                 "texto": "voyage-4-large com 1024 dimensoes, "
                          "numCandidates=150, quantizacao escalar."},
     "conclusao": "Nao existe 'textual OU vetorial' — o Atlas executa os dois e funde no servidor"},

    {"tipo": "definicao_fluxo",
     "eyebrow": "ciclo 2 · fusao e relevancia",
     "titulo": "Como os dois resultados se tornam um contexto",
     "subtitulo": "$rankFusion (RRF) no Atlas e rerank condicional antes de chamar o LLM redator.",
     "definicao": {"rotulo": "busca hibrida",
                   "frase": "Uma unica ida ao Atlas: os dois ramos rodam e sao fundidos no servidor.",
                   "legenda": "O embedding da pergunta e gerado dentro do "
                              "$vectorSearch (autoEmbed) — nenhuma chamada previa.",
                   "titulo_direita": "combinacao dos resultados"},
     "etapas": [
         "Reciprocal Rank Fusion: score = soma de peso / (60 + posicao) em cada ramo",
         "Deduplicacao nativa — o chunk achado pelas duas vias soma os dois ramos e sobe",
         "Rerank condicional: pulado quando o melhor score >= RERANK_SKIP_SCORE",
         "rerank-2.5 reordena e corta o contexto em limite = 6 chunks"],
     "nota": {"rotulo": "por que condicional",
              "texto": "Vencedor claro dispensa uma ida a API."}},

    {"tipo": "codigo",
     "eyebrow": "ciclo 2 · indice textual",
     "titulo": "Quatro caminhos de busca dentro de um unico $search",
     "subtitulo": "_busca_txt_raw() — compound.should soma a pontuacao de todas "
                  "as clausulas que casam.",
     "arquivo": "tools_dodf.py · _busca_txt_raw()",
     "codigo": """FUZZY = {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50}

pipe = [
    {"$search": {"index": "busca_textual", "compound": {"should": [
        # 1. texto com tolerancia a erro de digitacao
        {"text": {"query": q, "path": "texto", "fuzzy": FUZZY}},
        # 2. analisador fonetico: som do nome (Souza / Sousa)
        {"text": {"query": q, "path": "texto.fonetico"}},
        # 3. sem acento e minusculas, tambem com fuzzy
        {"text": {"query": q, "path": "texto.normalizado", "fuzzy": FUZZY}},
        # 4. expressao exata: pontua mais alto quem tem a frase
        {"phrase": {"query": q, "path": "texto"}}
    ]}}},
    {"$project": {"texto": 1, "metadados": 1,
                  "score": {"$meta": "searchScore"}}},
    {"$limit": lim}
]""",
     "rotulo_notas": "leitura",
     "notas": [
         {"titulo": "should, nao must",
          "texto": "Nenhuma clausula e obrigatoria: quem casa em mais caminhos "
                   "sobe no ranking."},
         {"titulo": "maxEdits 2",
          "texto": "Duas edicoes de distancia cobrem 'Gonsalves' para "
                   "'Goncalves'; prefixLength 1 protege a performance."},
         {"titulo": "fonetico",
          "texto": "Analisador definido no indice — nao existe campo "
                   "texto.fonetico gravado no documento."},
         {"titulo": "lim = limite x 3",
          "texto": "busca_rapida_paralela pede no minimo 15 resultados para o "
                   "rerank ter margem de escolha."}]},

    {"tipo": "definicao_linhas",
     "eyebrow": "ciclo 2 · fusao",
     "titulo": "Do $rankFusion ao corte em seis trechos",
     "subtitulo": "busca_rapida_paralela() — o que acontece entre a busca hibrida "
                  "e o LLM redator.",
     "definicao": {"rotulo": "regra de combinacao",
                   "frase": "Pesos iguais por padrao: nenhum ramo tem prioridade sobre o outro.",
                   "legenda": "RANKFUSION_PESO_TEXTUAL / _SEMANTICO no .env "
                              "ajustam o equilibrio sem mudar codigo."},
     "linhas": [
         {"rotulo": "fundir",
          "texto": "RRF no servidor: quem aparece nos dois ramos soma as duas contribuicoes e lidera."},
         {"rotulo": "limitar",
          "texto": "Uniao dos ramos (ate 2 x lim) — mesmo pool de candidatos que a fusao no cliente."},
         {"rotulo": "cortar",
          "texto": "Com rerank, top_k = limite; sem rerank, um simples comb[:limite]."}],
     "faixa": "Fallback automatico: se o stage falhar (cluster < 8.1), duas consultas em paralelo "
              "com fusao no cliente.",
     "fundo": "branco"},

    {"tipo": "codigo",
     "eyebrow": "ciclo 2 · relevancia",
     "titulo": "O rerank e uma chamada que o sistema tenta evitar",
     "subtitulo": "Tres condicoes precisam ser verdadeiras para a Voyage ser "
                  "acionada de novo.",
     "arquivo": "tools_dodf.py · busca_rapida_paralela()",
     "codigo": """t0 = time.time()
comb = None
if CFG.RANKFUSION_ENABLED:
    try:                                     # $search + $vectorSearch, RRF no Atlas
        comb = _busca_fusao_raw(col, consulta, lim_busca, filtros)
    except Exception:
        comb = None
if comb is None:                             # fallback: 2 consultas em paralelo
    comb = _busca_paralela_cliente(col, consulta, lim_busca, filtros)
_timings_atual.append({"ferramenta": "rankfusion_mongodb",
                       "tempo_ms": int((time.time() - t0) * 1000)})

# vencedor claro dispensa uma ida a API de rerank
melhor_sem = max((r.get("score_sem", 0) for r in comb), default=0)
pular_rerank = (CFG.RERANK_SKIP_SCORE > 0
                and melhor_sem >= CFG.RERANK_SKIP_SCORE)

if CFG.RERANK_ENABLED and len(comb) > limite and not pular_rerank:
    comb = rerancar(consulta, comb, top_k=limite)    # rerank-2.5
else:
    comb = comb[:limite]""",
     "rotulo_notas": "leitura",
     "notas": [
         {"titulo": "$rankFusion",
          "texto": "MongoDB 8.1+: os dois ramos rodam no servidor e voltam ja "
                   "fundidos e deduplicados em uma unica resposta."},
         {"titulo": "RERANK_SKIP_SCORE = 0",
          "texto": "Zero desliga o atalho. Acima disso, define o quao confiante "
                   "o vetor precisa estar."},
         {"titulo": "len(comb) > limite",
          "texto": "Se ja sobraram seis trechos ou menos, nao ha o que "
                   "reordenar: o rerank e dispensavel."},
         {"titulo": "Tempo por etapa",
          "texto": "Busca e rerank registram tempo_ms separadamente em "
                   "_timings_atual."}]},



    {"tipo": "tabela",
     "eyebrow": "auditoria",
     "titulo": "Onde cada indice e fixado no codigo",
     "subtitulo": "Em nenhum ponto do fluxo o LLM informa qual indice usar.",
     "colunas": [{"nome": "Ponto do codigo", "largura": 3.4},
                 {"nome": "Indice", "largura": 2.4},
                 {"nome": "Origem do nome", "largura": 3.3},
                 {"nome": "Quem decide", "largura": 2.2}],
     "linhas": [
         ["tools_dodf · _busca_txt_raw", "busca_textual",
          "String literal no pipeline", "Codigo"],
         ["tools_dodf · _busca_sem_raw", "busca_vetorial",
          "CFG.VECTOR_INDEX_NAME (.env)", "Configuracao"],
         ["tools_dodf · verificar_cache", "cache_vetorial",
          "CFG.CACHE_INDEX_NAME (.env)", "Configuracao"],
         ["tools_dodf · _consultar_atos", "B-tree da colecao atos",
          "Planner do MongoDB", "Otimizador"],
         ["chatbot · pipeline_rapido", "— (roteamento)",
          "Substring + limiar", "Codigo"]],
     "nota": {"rotulo": "modo agente",
              "texto": "O LLM escolhe a ferramenta pela docstring, mas os "
                       "argumentos sao nomeados e tipados."},
     "rodape_txt": "A ferramenta consultar_atos chama o mesmo _consultar_atos() "
                   "usado pela rota rapida."},

    {"tipo": "duas_colunas",
     "eyebrow": "ciclo 2 · redacao",
     "titulo": "O que o LLM redator recebe — e o que ele nao pode fazer",
     "subtitulo": "PROMPT_RAPIDO + trechos formatados por _fmt(): a fronteira da "
                  "resposta e o contexto.",
     "coluna_clara": {
         "rotulo": "o que entra no prompt",
         "itens": [
             {"titulo": "Os trechos com procedencia",
              "descricao": "[TRECHO 1 | Fonte: DODF 015 22-01-2025 INTEGRA.pdf, "
                           "Pagina 37 | Score: ... | Rerank: ...]"},
             {"titulo": "800 caracteres por trecho",
              "descricao": "_fmt() corta cada trecho — o contexto cabe na janela "
                           "sem competir com a instrucao."},
             {"titulo": "Historico resumido",
              "descricao": "Ate 200 caracteres por mensagem anterior, para "
                           "perguntas de acompanhamento."},
             {"titulo": "A pergunta original",
              "descricao": "Sem reescrita: a pergunta do usuario chega ao "
                           "redator como foi digitada."}]},
     "coluna_escura": {
         "rotulo": "o que o prompt proibe",
         "itens": [
             {"titulo": "Responder fora dos trechos",
              "descricao": "'Responda SOMENTE com base nos trechos fornecidos. "
                           "NAO invente.'"},
             {"titulo": "Omitir a fonte",
              "descricao": "'SEMPRE cite fonte: (Fonte: arquivo, Pagina X)' — a "
                           "citacao e parte do formato exigido."},
             {"titulo": "Aproximar dados",
              "descricao": "'EXTRAIA dados exatos' — numero, nome e data vem do "
                           "trecho, nao de parafrase."},
             {"titulo": "Escolher indice ou filtro",
              "descricao": "Nada disso esta no prompt: rota, indice e limiar ja "
                           "foram decididos pelo codigo."}]},
     "rodape_txt": "chatbot.py · PROMPT_RAPIDO — o prompt tambem pode vir da "
                   "colecao prompt_templates via carregar_prompt()."},

    {"tipo": "tabela",
     "eyebrow": "desempenho",
     "titulo": "Latencia por rota",
     "subtitulo": "Medicoes da colecao metricas — a camada MongoDB nao e o gargalo.",
     "colunas": [{"nome": "Rota", "largura": 2.2},
                 {"nome": "Caminho", "largura": 5.0},
                 {"nome": "Chamadas externas", "largura": 2.3},
                 {"nome": "Latencia", "largura": 1.8}],
     "linhas": [
         ["Cumprimento", "Resposta canned em chatbot.py", "0", "< 0,1 s"],
         ["Cache", "$vectorSearch em cache_semantico", "1 (embedding)", "~1,3 s"],
         ["Analitica", "nl2query + $group na colecao atos",
          "2 (LLM + embedding)", "~2,8 s"],
         ["Semantica", "$search e $vectorSearch em paralelo + rerank + redacao",
          "3 a 4", "~11,9 s"]],
     "nota": {"rotulo": "leitura",
              "texto": "O tempo esta nas APIs de embedding, rerank e redacao — "
                       "por isso a V2 atacou chamadas, nao tamanho de cluster."},
     "rodape_txt": "Timings registrados por ferramenta em _timings_atual e "
                   "persistidos na colecao metricas."},

    {"tipo": "cards_numerados",
     "eyebrow": "operacao",
     "titulo": "Toda pergunta deixa rastro em tres colecoes",
     "subtitulo": "A telemetria nao e um add-on: e escrita pelo mesmo codigo que "
                  "executa a consulta.",
     "cards": [
         {"rotulo": "metricas · 30 dias",
          "texto": "session_id, ferramentas_usadas, modelo, tempo_total_ms e "
                   "cache_hit. TTL de 30 dias."},
         {"rotulo": "auditoria · rastro completo",
          "texto": "Pergunta, resposta, modo de busca, turno e as fontes .pdf "
                   "extraidas do texto por regex."},
         {"rotulo": "feedback · avaliacao",
          "texto": "O voto do usuario e gravado e tambem anexado ao documento "
                   "de auditoria daquela pergunta."}],
     "destaque": {"rotulo": "como e medido",
                  "texto": "O decorator _track_tempo envolve as 10 ferramentas e "
                           "acumula tempo_ms e sucesso em _timings_atual."},
     "rodape_txt": "Falha ao gravar telemetria nunca interrompe a resposta: todas "
                   "as escritas estao em try/except silencioso."},

    {"tipo": "definicao_fluxo",
     "eyebrow": "operacao · citacao",
     "titulo": "A citacao abre o PDF na pagina exata",
     "subtitulo": "chatbot.py serve o binario do GridFS em uma thread HTTP "
                  "dentro do proprio processo Streamlit.",
     "definicao": {"rotulo": "verificabilidade",
                   "frase": "A resposta nao pede confianca: ela entrega o documento original.",
                   "legenda": "Sem esse elo, o sistema seria apenas mais um "
                              "gerador de texto plausivel.",
                   "titulo_direita": "do trecho ao documento"},
     "etapas": [
         "O chunk carrega metadados.arquivo e metadados.pagina",
         "link_pdf() monta a URL com #page=N e &search=<primeiras palavras>",
         "_GridFSHandler busca por filename e devolve o PDF em stream",
         "st.cache_resource garante um unico servidor entre reruns"],
     "nota": {"rotulo": "porta",
              "texto": "CFG.PDF_SERVER_PORT = 8502."},
     "fundo": "branco"},


    {"tipo": "duas_colunas",
     "eyebrow": "numeros",
     "titulo": "A base hoje e o que a V2 mudou",
     "subtitulo": "Estatisticas medidas nas colecoes documentos e pdfs.",
     "fundo": "branco",
     "coluna_clara": {
         "rotulo": "a base hoje",
         "itens": [
             {"titulo": "124 edicoes · 6.435 paginas",
              "descricao": "Cada PDF preservado no GridFS e servido na pagina citada."},
             {"titulo": "51.714 chunks",
              "descricao": "Media de 8,0 chunks por pagina; 8,8 considerando so "
                           "paginas com texto extraivel."},
             {"titulo": "1.110 caracteres por chunk",
              "descricao": "Mediana 1.330 e p95 1.489 — o splitter aproveita "
                           "quase todo o CHUNK_SIZE."},
             {"titulo": "57,4 milhoes de caracteres",
              "descricao": "Indexados simultaneamente por texto e por vetor."}]},
     "coluna_escura": {
         "rotulo": "o que a v2 mudou",
         "itens": [
             {"titulo": "Ingestao paralela",
              "descricao": "Paginas e lotes de embedding concorrentes."},
             {"titulo": "Quantizacao escalar",
              "descricao": "Indice vetorial menor, recall preservado."},
             {"titulo": "Pool de conexoes",
              "descricao": "Cliente unico reaproveitado entre reruns do Streamlit."},
             {"titulo": "Rerank condicional e reforco de atos",
              "descricao": "Menos idas a API na consulta; mais cobertura "
                           "estruturada na ingestao."}]},
     "rodape_txt": "CHUNK_SIZE=1500 · CHUNK_OVERLAP=300 · VOYAGE_EMBEDDING_BATCH=128."},

    {"tipo": "dois_conceitos",
     "eyebrow": "fechamento",
     "titulo": "Quem decide o que",
     "subtitulo": "A divisao de responsabilidade e o que torna o sistema auditavel.",
     "esquerda": {"sigla": "LLM", "nome": "interpreta e redige",
                  "frase": "Extrai parametros e escreve a resposta final.",
                  "rotulo": "restricao",
                  "texto": "So ve os trechos recuperados. O PROMPT_RAPIDO proibe "
                           "responder fora deles e exige a citacao (arquivo, pagina)."},
     "direita": {"sigla": "CODIGO", "nome": "decide e executa",
                 "frase": "Escolhe rota, indice, filtro e limiar.",
                 "rotulo": "garantia",
                 "texto": "Pipeline literal, valores validados e telemetria por "
                          "ferramenta persistida na colecao metricas."},
     "conclusao": "A contagem vem de um $group do MongoDB — nao de uma estimativa do modelo"},
]


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    for d in CONTEUDO:
        LAYOUTS[d["tipo"]](prs, d)
    prs.save(SAIDA)
    print(f"OK: {SAIDA} — {len(CONTEUDO)} slides")


if __name__ == "__main__":
    main()
