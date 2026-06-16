# 🏛️ DODF Search — Casa Civil do Distrito Federal

Sistema de busca inteligente do **Diário Oficial do Distrito Federal (DODF)**, com
assistente conversacional (RAG), busca híbrida (semântica + textual) e pipeline de
indexação de PDFs. Construído sobre **MongoDB Atlas**, **Voyage AI** e **LangGraph**.

---

## 📦 Componentes

| Arquivo | Descrição |
|---|---|
| `config.py` | Configuração central: MongoClient, GridFS, embeddings/rerank Voyage 4 |
| `setup_mongodb.py` | Cria coleções, índices auxiliares e o prompt do agente (v5) |
| `processar_pdf.py` | Pipeline de extração, limpeza, chunking e indexação de PDFs |
| `monitor_pasta.py` | Processa PDFs existentes e monitora a pasta para novos arquivos |
| `tools_dodf.py` | 10 ferramentas de busca usadas pelo agente |
| `chatbot.py` | App Streamlit (4 páginas) — ponto de entrada |
| `iniciar.sh` | Orquestra Streamlit + monitor + Ollama (start/stop/status) |

---

## ✅ Pré-requisitos

- **Python 3.11+**
- **Conta no MongoDB Atlas** com um cluster (vector search habilitado)
- **Chave da Voyage AI** (ou via MongoDB Atlas) para embeddings e reranking
- **Chave da Anthropic e/ou Google** (Claude / Gemini) — opcional
- **Ollama** (opcional) para LLM local de fallback — `brew install ollama`

---

## 🚀 Instalação

```bash
git clone https://github.com/marcoslopes-creator/Dodf-search.git
cd Dodf-search

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## ⚙️ Configuração (.env)

Copie o modelo e preencha com suas credenciais:

```bash
cp .env.example .env
nano .env
```

Variáveis principais:

| Variável | Descrição |
|---|---|
| `MONGODB_URI` | String de conexão do Atlas |
| `MONGODB_DB` / `MONGODB_COLLECTION` | Banco e coleção de documentos |
| `VOYAGE_API_KEY` | Chave da Voyage AI |
| `VOYAGE_API_PROVIDER` | `atlas` (ai.mongodb.com) ou `voyage` (api.voyageai.com) |
| `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` | LLMs em nuvem (opcionais) |
| `LLM_MODEL` | Modelo Ollama de fallback (ex: `gemma4:26b`) |
| `PDF_FOLDER` | Pasta monitorada para ingestão automática de PDFs |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | Parâmetros de chunking (1500 / 300) |

> ⚠️ O `.env` **nunca** é versionado (está no `.gitignore`). Veja todas as
> variáveis em [`.env.example`](.env.example).

---

## 🔎 Índices do Atlas Search

A busca depende de **3 índices** criados manualmente no MongoDB Atlas (UI ou API).
Eles **não estão versionados** (veja a seção [Detalhes fora do repositório](#-detalhes-que-ficaram-fora-do-repositório)).

1. **`busca_vetorial`** — coleção `documentos` (Vector Search, 1024 dim, cosine):
```json
{ "fields": [
  { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
  { "type": "filter", "path": "metadados.arquivo" },
  { "type": "filter", "path": "metadados.pagina" }
]}
```

2. **`cache_vetorial`** — coleção `cache_semantico` (Vector Search):
```json
{ "fields": [
  { "type": "vector", "path": "pergunta_embedding", "numDimensions": 1024, "similarity": "cosine" }
]}
```

3. **`busca_textual`** — coleção `documentos` (Atlas Search, analisador
   `lucene.brazilian` + analisadores fonético e normalizado/stemming). Definição
   completa fica no arquivo `indice_busca_textual.json` (não versionado).

---

## 🗄️ Setup inicial do MongoDB

Cria coleções, índices auxiliares e insere o prompt do agente:

```bash
python setup_mongodb.py
```

---

## 📥 Indexação de PDFs

Configure `PDF_FOLDER` no `.env` e rode o monitor. Ele processa todos os PDFs
existentes na pasta e continua monitorando novos arquivos:

```bash
PYTHONUNBUFFERED=1 python monitor_pasta.py
# Ctrl+C para encerrar o monitoramento
```

> Também é possível enviar PDFs pela página **📤 Upload PDFs** da interface.

---

## ▶️ Executando a aplicação

**Opção A — script orquestrador (recomendado, macOS/Linux):**

```bash
./iniciar.sh                 # sobe Streamlit + monitor + Ollama
./iniciar.sh --sem-ollama    # sem LLM local
./iniciar.sh --sem-monitor   # sem monitor de pasta
./iniciar.sh --status        # status dos serviços
./iniciar.sh --parar         # para tudo
```

**Opção B — Streamlit direto:**

```bash
streamlit run chatbot.py
```

Acesse: **http://localhost:8501** (servidor de PDFs embutido em `:8502`).

---

## 🖥️ Páginas da interface

| Página | Função |
|---|---|
| 💬 **Chat (com IA)** | Assistente RAG com agente LangGraph; escolha de modelo (Claude / Gemini / Local), modo rápido ou agente, e cache semântico |
| 🔍 **Busca Textual** | Busca direta (fuzzy / fonética / stemming) sem IA |
| 📤 **Upload PDFs** | Envio e indexação de novos documentos com progresso |
| 📋 **Auditoria** | Consultas, métricas de performance e feedback |

---

## 🔒 Detalhes que ficaram fora do repositório

Os itens abaixo estão no `.gitignore` e **não foram enviados ao GitHub**. Para
rodar o projeto em outra máquina, você precisa recriá-los:

| Item | Por que ficou de fora | Como obter/recriar |
|---|---|---|
| `.env` | Contém chaves de API e a `MONGODB_URI` | Copie de `.env.example` e preencha |
| `dodf_poc.zip` (165 MB) | Excede o limite de 100 MB do GitHub | Armazenar fora do Git (ex: Git LFS, storage externo) |
| `files.zip` | Pacote local de arquivos | Reproduzir conforme necessidade |
| `indice_*.json` | Definições de índices do Atlas | Recriadas via Atlas (veja [Índices](#-índices-do-atlas-search)) |
| `venv/` | Ambiente virtual local | `python3 -m venv venv && pip install -r requirements.txt` |
| `logs/`, `.pids/` | Logs e PIDs em tempo de execução | Gerados automaticamente ao rodar |

> 💡 Se as chaves de API já foram expostas em algum momento, **rotacione-as** nos
> respectivos painéis (Voyage, Anthropic, Google, MongoDB Atlas).

---

## 🏗️ Stack técnica

- **Banco vetorial:** MongoDB Atlas (Vector Search + Atlas Search) + GridFS para PDFs
- **Embeddings:** Voyage `voyage-4-large` (1024 dim)
- **Reranking:** Voyage `rerank-2.5`
- **LLMs:** Claude (Anthropic), Gemini (Google) ou Ollama local (fallback)
- **Agente:** LangGraph (ReAct) com 10 ferramentas e checkpoint de memória
- **Interface:** Streamlit
