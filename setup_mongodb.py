"""
setup_mongodb.py — Setup do MongoDB
=====================================
Cria colecoes, indices e prompt do agente.
Execute uma vez antes de processar PDFs.

Uso: python setup_mongodb.py
"""

from datetime import datetime
from pymongo import ASCENDING
from config import get_db, CFG


PROMPT_AGENTE = """Voce e o assistente oficial da Casa Civil do Distrito Federal, especializado EXCLUSIVAMENTE no Diario Oficial do Distrito Federal (DODF).

IDENTIDADE:
- Voce representa a Casa Civil do DF, orgao responsavel pelo DODF.
- Tom: profissional, formal e cordial.

ESCOPO:
- Responda SOMENTE perguntas sobre o DODF.
- Para outros assuntos: "Sou o assistente da Casa Civil do DF, especializado no Diario Oficial. Posso ajudar com decretos, portarias, nomeacoes, exoneracoes, licitacoes e demais publicacoes."
- NAO busque informacoes na internet.

CORDIALIDADE:
- Cumprimente de forma cordial e breve.
- Apos cumprimentar, lembre o usuario do que voce pode fazer.

FERRAMENTAS DISPONIVEIS (10):
1. consultar_atos — CONSULTA PRECISA com contagem exata (PRIORIDADE para contagens!)
2. busca_hibrida — Primeira opcao para perguntas simples
3. busca_textual_fuzzy — Nomes proprios com erro de digitacao
4. busca_semantica — Sinonimos, linguagem natural
5. busca_estruturada — Multiplos criterios em texto livre
6. contar_e_agrupar — Contagem simples por um termo
7. buscar_em_arquivo — Busca em PDF especifico
8. estatisticas_base — Info sobre a base
9. resumo_conversa — Perguntas de acompanhamento
10. refinar_busca — Sugere estrategias alternativas

REGRA DE OURO:
Para QUALQUER pergunta de CONTAGEM ou LISTAGEM ('quantos', 'liste', 'quais', 'algum X foi nomeado/exonerado'), USE 'consultar_atos' PRIMEIRO.

EXEMPLOS:
  - "quantos pedros nomeados em 2025" -> consultar_atos(nome_pessoa='pedro', tipo_ato='nomeacao', ano='2025')
  - "pedro exonerado medico maio 2025" -> consultar_atos(nome_pessoa='pedro', tipo_ato='exoneracao', cargo='medico', ano='2025', mes='maio')
  - "exoneracoes janeiro 2026" -> consultar_atos(tipo_ato='exoneracao', ano='2026', mes='janeiro')

REGRAS:
1. Responda EXCLUSIVAMENTE com base nos resultados das ferramentas.
2. EXTRAIA dados exatos: numeros, datas, nomes completos.
3. SEMPRE cite fonte: (Fonte: nome_arquivo, Pagina X).
4. NAO invente. NAO deduza.

IDIOMA: Portugues brasileiro formal."""


def setup():
    print("Conectando ao MongoDB Atlas...")
    db = get_db()

    # Colecoes com TTL
    print("\n1. cache_semantico (TTL 7 dias)...")
    col = db["cache_semantico"]
    try:
        col.create_index("ttl", expireAfterSeconds=0)
    except Exception:
        pass
    print(f"   {col.count_documents({})} docs")

    print("\n2. historico_sessoes (TTL 7 dias)...")
    col = db["historico_sessoes"]
    try:
        col.create_index("ttl", expireAfterSeconds=0)
        col.create_index("session_id", unique=True)
    except Exception:
        pass
    print(f"   {col.count_documents({})} docs")

    print("\n3. metricas (TTL 30 dias)...")
    col = db["metricas"]
    try:
        col.create_index("ttl", expireAfterSeconds=0)
        col.create_index([("timestamp", ASCENDING)])
    except Exception:
        pass
    print(f"   {col.count_documents({})} docs")

    print("\n4. feedback...")
    col = db["feedback"]
    try:
        col.create_index([("timestamp", ASCENDING)])
    except Exception:
        pass
    print(f"   {col.count_documents({})} docs")

    print("\n5. auditoria (permanente)...")
    col = db["auditoria"]
    for idx in ["timestamp", "session_id", "modelo", "sucesso", "feedback.avaliacao"]:
        try:
            col.create_index([(idx, ASCENDING)])
        except Exception:
            pass
    print(f"   {col.count_documents({})} docs")

    # Colecao pdfs (metadados de PDFs)
    print("\n6. pdfs (metadados)...")
    col = db["pdfs"]
    for idx in ["nome_arquivo", "status", "data_upload"]:
        try:
            col.create_index([(idx, ASCENDING)])
        except Exception:
            pass
    try:
        col.create_index("hash_md5", unique=True)
    except Exception:
        pass
    print(f"   {col.count_documents({})} PDFs registrados")

    # Prompt do agente
    print("\n7. prompt_templates (v5)...")
    col = db["prompt_templates"]
    col.delete_many({"nome": "system_prompt_agente"})
    col.insert_one({
        "nome": "system_prompt_agente",
        "versao": 5,
        "ativo": True,
        "prompt": PROMPT_AGENTE,
        "descricao": "Voyage 4 Enterprise — consultar_atos prioritario",
        "criado_em": datetime.now()
    })
    print("   Prompt v5 inserido")

    # Colecao atos (extracao estruturada — Fase 1)
    print(f"\n8. {CFG.ATOS_COLLECTION} (atos estruturados)...")
    col = db[CFG.ATOS_COLLECTION]
    try:
        col.create_index([("nome_normalizado", ASCENDING),
                           ("tipo_ato", ASCENDING), ("ano", ASCENDING)])
        col.create_index([("tipo_ato", ASCENDING)])
        col.create_index([("ano", ASCENDING), ("mes", ASCENDING)])
        col.create_index([("orgao", ASCENDING)])
        col.create_index([("arquivo", ASCENDING)])
        col.create_index([("hash_arquivo", ASCENDING)])
    except Exception:
        pass
    print(f"   {col.count_documents({})} atos registrados")

    # Verifica documentos
    print("\n9. documentos...")
    col = db["documentos"]
    try:
        col.create_index([("metadados.arquivo", ASCENDING)])
        col.create_index([("hash_arquivo", ASCENDING)])
    except Exception:
        pass
    print(f"   Chunks: {col.count_documents({})}")
    print(f"   PDFs distintos: {len(col.distinct('metadados.arquivo'))}")

    print(f"\n{'='*50}\nSETUP CONCLUIDO\n{'='*50}")
    for nome in sorted(db.list_collection_names()):
        try:
            print(f"  - {nome}: {db[nome].count_documents({})} docs")
        except Exception:
            pass


if __name__ == "__main__":
    setup()
