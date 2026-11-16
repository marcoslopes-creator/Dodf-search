# CLAUDE.md — DODF Search

Sistema RAG sobre o Diario Oficial do Distrito Federal (DODF) para a Casa Civil do DF.
Stack: Python 3.11+ (venv local em 3.14), Streamlit, LangChain/LangGraph, MongoDB Atlas,
Voyage AI (via Atlas), Claude via gateway corporativo Grove. Codigo, UI e commits em portugues.

Documentos complementares (ler quando o assunto for operacao ou visual):
- `PROCEDIMENTO_COMPLETO.md` — procedimento operacional ponta a ponta
- `PROMPT-IDENTIDADE-VISUAL.md` — identidade visual MongoDB (verde #00ED64, navy #001E2B, fonte Lexend Deca)
- `README.md` — visao geral e pre-requisitos

## Arquitetura (principios que nao devem ser quebrados)

1. **MongoDB Atlas e o store unico**: texto dos chunks, embeddings, metadados, cache
   semantico, historico de sessoes, metricas, auditoria, feedback, prompt do agente e PDFs
   (GridFS). Nao introduzir outro banco, fila ou vector store.
2. **Embeddings sao gerados pelo Atlas (`autoEmbed`)**, nunca no cliente. Indices:
   `busca_vetorial` (campo `texto`, `voyage-4-large`, 1024d) e `cache_vetorial`
   (campo `pergunta`, `voyage-4-lite`). Definicoes em `indice_*.json`. Nao chamar API de
   embeddings em codigo Python.
3. **Busca hibrida server-side com `$rankFusion`** (`$search` textual `busca_textual`,
   analyzer `lucene.brazilian` + `$vectorSearch`), com pre-filtros de data/edicao em cada
   ramo. Fallback automatico para duas consultas paralelas + intercalacao se o stage falhar
   ou `RANKFUSION_ENABLED=false`. Exige cluster MongoDB >= 8.1 (atual: 9.0.4 / FCV 9.0, tier M10+).
4. **Rerank Voyage** (`config.rerancar`) e sempre a etapa final da busca.
5. **Claude so e instanciado por `config.criar_claude()`** — roteia para o Grove quando
   `GROVE_API_KEY` existe, senao API Anthropic direta. Nunca criar `ChatAnthropic` fora dele.
6. Fallbacks de LLM: Gemini (`GOOGLE_API_KEY`) e Ollama local (`LLM_MODEL`).

## Mapa de modulos

| Arquivo | Papel |
|---|---|
| `config.py` | `CFG` (todas as variaveis de ambiente), `criar_claude()`, `get_db()`, `get_gridfs()`, `rerancar()` |
| `chatbot.py` | App Streamlit, ponto de entrada. Paginas: `pagina_busca`, `pagina_chat`, `pagina_upload`, `pagina_auditoria`. Chat tem **Modo Rapido** (`pipeline_rapido`: cache -> nl2query -> `$rankFusion` -> rerank -> LLM, ~3 s) e **Modo Agente** (`create_react_agent` + `MemorySaver`, ~10-15 s). Sobe servidor HTTP de PDFs do GridFS na porta 8502 |
| `tools_dodf.py` | Busca (`busca_rapida_paralela`, `_busca_fusao_raw`, `_stage_search`, `_stage_vector`), cache semantico, historico, metricas, auditoria, feedback e as 10 ferramentas do agente em `TODAS_FERRAMENTAS` |
| `nl2query.py` | Interpretador de perguntas analiticas (filtros estruturados para `consultar_atos`) |
| `ui_theme.py` | Tema visual MongoDB; usa `assets/` |
| `processar_pdf.py`, `ocr.py`, `extrator_atos.py` | Extracao, OCR (Mistral), chunking, extracao de atos de pessoal |
| `ingestao_paralela.py`, `monitor_pasta.py` | Ingestao em lote e monitoramento da pasta `PDF_FOLDER` |
| `setup_mongodb.py` | Cria colecoes e grava `system_prompt_agente` (v5) em `prompt_templates` |
| `setup_indices_vetoriais.py` | Cria/atualiza indices Atlas Search e Vector Search a partir dos `indice_*.json` |
| `backfill_atos.py`, `reforco_atos.py` | Reprocessamento da colecao de atos |
| `gerar_apresentacao_arquitetura.py` | Gera `DODF-Search-Arquitetura.pptx` |
| `iniciar.sh` | start/stop/status de Streamlit (8501) + monitor + Ollama; logs em `logs/`, PIDs em `.pids/` |

Colecoes: `documentos`, `pdfs` (GridFS), `cache_semantico`, `historico_sessoes`, `metricas`,
`auditoria`, `feedback`, `prompt_templates`, atos em `ATOS_COLLECTION`.

Ferramentas do agente: `busca_hibrida`, `busca_textual_fuzzy`, `busca_semantica`,
`contar_e_agrupar`, `buscar_em_arquivo`, `estatisticas_base`, `resumo_conversa`,
`refinar_busca`, `busca_estruturada`, `consultar_atos` (prioritaria para atos de pessoal).

## Como rodar

```bash
source venv/bin/activate            # ou criar: python3 -m venv venv && pip install -r requirements.txt
./iniciar.sh                        # tudo; --sem-ollama, --sem-monitor, --parar, --status
venv/bin/streamlit run chatbot.py   # so o app (http://localhost:8501)
venv/bin/python -m py_compile tools_dodf.py config.py chatbot.py   # checagem rapida
venv/bin/python setup_mongodb.py && venv/bin/python setup_indices_vetoriais.py  # bootstrap
```

Nao ha suite de testes automatizados. Validacao e feita com perguntas de referencia na UI,
observando o painel de timings (linha `rankfusion_mongodb` ou `busca_paralela_mongodb`
indica qual caminho de busca foi usado) e a pagina de auditoria.

## Configuracao

- Tudo vem do `.env` (gitignored) via `CFG`. `.env.example` lista as chaves, mas esta
  **defasado**: faltam `GROVE_API_KEY`, `GROVE_BASE_URL`, `RANKFUSION_ENABLED`,
  `RANKFUSION_PESO_TEXTUAL`, `RANKFUSION_PESO_SEMANTICO`.
- Pesos dos ramos textual x semantico ajustam-se por `RANKFUSION_PESO_*`, sem mudar codigo.
- Nunca imprimir, logar ou commitar valores do `.env`.

## Convencoes de trabalho

- Mudancas conservadoras; respeitar estilo e densidade de comentarios existentes.
- Nao adicionar dependencias sem confirmar com o usuario; usar `pip` para instalar, nunca
  editar `requirements.txt` a mao.
- Nao criar arquivos `.md` ou de documentacao alem dos existentes salvo pedido explicito.
- Scripts temporarios de teste: prefixo `_teste_*_tmp.py` e remover ao final.
- Ao mexer na busca, preservar: pre-filtros em cada ramo, pool de candidatos `2 x limite`
  antes do rerank, fallback cliente, rerank como etapa final.
- Arquivos obsoletos ficam em `../dodf-search-old/` (fora do repo), nunca em `Backup/`.

## Estado atual e pendencias

- Concluido: autoEmbed, retrieval assimetrico (large/lite), `$rankFusion` server-side,
  pre-filtros de metadados, remocao de embeddings no cliente, Grove como gateway unico.
- `PROCEDIMENTO_COMPLETO.md` cita `migrar_voyage.py` e `extrair_atos.py`, que nao existem
  (o modulo real e `extrator_atos.py`) — documento precisa de atualizacao.
- `.gitignore` ainda lista `Backup/` e um `.md` ja movidos (inofensivo).
- `MemorySaver` do Modo Agente e em memoria (perde contexto ao reiniciar). Opcao avaliada:
  `langgraph-checkpoint-mongodb` (`MongoDBSaver`), nao implementada.
- **Atlas Agent Engine** (Public Preview, nao recomendado para producao): avaliado.
  Decisao recomendada e nao implementada: entrypoint fino `agente_engine.py` com
  `agent-engine-sdk-langgraph` apenas para o Modo Agente, reutilizando `TODAS_FERRAMENTAS`
  e `criar_claude()`; `chatbot.py` inalterado; Modo Rapido fora do Agent Engine.
  Memory Service descartado (baixo valor para perguntas factuais ao DODF).
