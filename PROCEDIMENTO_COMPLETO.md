# 🏛️ DODF Search — Procedimento Completo de Recriação

> Casa Civil do Distrito Federal — Voyage 4 Enterprise

## Sumário

1. [Visão geral dos arquivos](#1-arquivos)
2. [⚠️ Limpeza de segurança (CRÍTICO)](#2-seguranca)
3. [Limpeza do ambiente atual](#3-limpeza-ambiente)
4. [Configuração do .env](#4-env)
5. [Configuração dos índices Atlas Search](#5-indices)
6. [Instalação dos arquivos](#6-instalacao)
7. [Setup inicial](#7-setup)
8. [Processamento dos PDFs](#8-processamento)
9. [Iniciar a aplicação](#9-iniciar)
10. [Testes finais](#10-testes)
11. [Resolução de problemas](#11-troubleshooting)

---

## 1. Arquivos {#1-arquivos}

São **8 arquivos** nesta entrega:

| # | Arquivo | Tipo | Descrição |
|---|---|---|---|
| 1 | `config.py` | Python | Configuração centralizada + MongoClient + Voyage 4 |
| 2 | `setup_mongodb.py` | Python | Cria coleções, índices, prompt v5 |
| 3 | `processar_pdf.py` | Python | Pipeline de PDFs com limpeza O(n) |
| 4 | `monitor_pasta.py` | Python | Monitora pasta de PDFs |
| 5 | `tools_dodf.py` | Python | 10 ferramentas + utilitários |
| 6 | `chatbot.py` | Python | App Streamlit (4 páginas) |
| 7 | `env.exemplo` | Texto | Template do .env (sem keys reais) |
| 8 | `indice_*.json` | JSON | 3 índices Atlas Search |

---

## 2. ⚠️ Limpeza de segurança (CRÍTICO) {#2-seguranca}

**Suas API keys foram expostas em conversas anteriores.** Antes de qualquer coisa:

### 2.1. Revogue TODAS as keys atuais

| Serviço | URL | Ação |
|---|---|---|
| Anthropic | https://console.anthropic.com/settings/keys | Delete a key atual |
| Google AI Studio | https://aistudio.google.com/apikey | Delete a key atual |
| Voyage AI | https://dash.voyageai.com/api-keys | Delete + crie nova |
| MongoDB Atlas | Database Access | Mude a senha do `dodf_admin` (atual `dodf_admin` é fraca!) |

### 2.2. Crie keys novas e GUARDE-AS COM SEGURANÇA

Anote em um gerenciador de senhas (1Password, Bitwarden, etc.). **Nunca cole em chat.**

### 2.3. Adicione `.env` ao `.gitignore`

```bash
cd ~/Projetos/dodf-search
echo ".env" >> .gitignore
echo "venv/" >> .gitignore
echo "__pycache__/" >> .gitignore
```

---

## 3. Limpeza do ambiente atual {#3-limpeza-ambiente}

### 3.1. Pare processos rodando

```bash
# Mata o streamlit se estiver aberto
pkill -f streamlit

# Mata Python que pode estar rodando processamento
pkill -f "python processar_pdf"
pkill -f "python migrar_voyage"
pkill -f "python monitor_pasta"
```

### 3.2. Limpe o MongoDB Atlas

```bash
cd ~/Projetos/dodf-search && source venv/bin/activate

# Use o config.py NOVO (precisa estar instalado primeiro - veja seção 6)
# Por enquanto, vamos usar pymongo direto:
python << 'EOF'
import os
from pymongo import MongoClient
from dotenv import load_dotenv
load_dotenv()

c = MongoClient(os.getenv("MONGODB_URI"))
db = c[os.getenv("MONGODB_DB", "dodf_database")]

# Lista o que existe antes
print("Estado atual:")
for nome in db.list_collection_names():
    print(f"  - {nome}: {db[nome].count_documents({})}")

resp = input("\nDeletar TODAS as coleções? (s/N): ")
if resp.lower() == "s":
    for nome in db.list_collection_names():
        db.drop_collection(nome)
        print(f"  ✓ {nome} dropada")
    print("\nLimpeza concluida.")
else:
    print("Cancelado.")
c.close()
EOF
```

### 3.3. Delete os arquivos antigos do projeto

```bash
cd ~/Projetos/dodf-search

# Backup opcional
mkdir -p ~/backup-dodf-$(date +%Y%m%d)
cp -r . ~/backup-dodf-$(date +%Y%m%d)/ 2>/dev/null

# Remove os arquivos antigos
rm -f config.py setup_mongodb.py processar_pdf.py monitor_pasta.py
rm -f tools_dodf.py chatbot.py migrar_voyage.py
rm -f extrair_atos.py
rm -rf static .streamlit
rm -rf __pycache__
```

---

## 4. Configuração do .env {#4-env}

### 4.1. Copie o template

```bash
cp ~/Downloads/env.exemplo ~/Projetos/dodf-search/.env
```

### 4.2. Edite com SUAS keys novas

```bash
nano ~/Projetos/dodf-search/.env
```

Substitua:
- `MONGODB_URI` — sua URI com **senha nova e forte**
- `VOYAGE_API_KEY` — sua nova chave Voyage
- `ANTHROPIC_API_KEY` — sua nova chave Anthropic
- `GOOGLE_API_KEY` — sua nova chave Google
- `PDF_FOLDER` — caminho **absoluto**: `/Users/marcos.lopes/Documentos/DODF`

Salve (Ctrl+O, Enter, Ctrl+X).

---

## 5. Configuração dos índices Atlas Search {#5-indices}

São **3 índices** no MongoDB Atlas. Vá em:
https://cloud.mongodb.com → seu cluster → **Atlas Search** tab

### 5.1. Delete os índices antigos

Se existirem `busca_textual`, `busca_vetorial`, `cache_vetorial` — delete os 3 (três pontos → Drop).

### 5.2. Crie `busca_textual` (na coleção `documentos`)

1. **Create Search Index** → **Atlas Search** → **JSON Editor** → Next
2. Database: `dodf_database`, Collection: `documentos`
3. Index Name: `busca_textual`
4. Cole o conteúdo de **`indice_busca_textual.json`**
5. Create → aguarde "Active"

### 5.3. Crie `busca_vetorial` (na coleção `documentos`) — **CRÍTICO**

1. **Create Search Index** → **Atlas Vector Search** (NÃO Atlas Search!) → JSON Editor → Next
2. Database: `dodf_database`, Collection: `documentos`
3. Index Name: `busca_vetorial`
4. Cole o conteúdo de **`indice_busca_vetorial.json`** (1024 dimensões)
5. Create → aguarde "Active"

### 5.4. Crie `cache_vetorial` (na coleção `cache_semantico`)

1. **Create Search Index** → **Atlas Vector Search** → JSON Editor → Next
2. Database: `dodf_database`, Collection: `cache_semantico`
3. Index Name: `cache_vetorial`
4. Cole o conteúdo de **`indice_cache_vetorial.json`**
5. Create → aguarde "Active"

> ⏳ Os índices ficam em status "Building" por alguns minutos. Não bloqueia os próximos passos.

---

## 6. Instalação dos arquivos {#6-instalacao}

```bash
cd ~/Projetos/dodf-search && source venv/bin/activate

# Copia os 6 arquivos Python
cp ~/Downloads/config.py .
cp ~/Downloads/setup_mongodb.py .
cp ~/Downloads/processar_pdf.py .
cp ~/Downloads/monitor_pasta.py .
cp ~/Downloads/tools_dodf.py .
cp ~/Downloads/chatbot.py .

# Garante que dependências estão instaladas
pip install --upgrade pymongo gridfs streamlit watchdog \
  langchain-core langchain-ollama langchain-anthropic \
  langchain-google-genai langgraph langchain-text-splitters \
  pymupdf python-dotenv requests
```

---

## 7. Setup inicial {#7-setup}

```bash
cd ~/Projetos/dodf-search && source venv/bin/activate

# Cria coleções, índices auxiliares e prompt v5
python setup_mongodb.py
```

Saída esperada:
```
SETUP CONCLUIDO
  - auditoria: 0 docs
  - cache_semantico: 0 docs
  - documentos: 0 docs
  - feedback: 0 docs
  - historico_sessoes: 0 docs
  - metricas: 0 docs
  - pdfs: 0 docs
  - prompt_templates: 1 docs
```

### Teste a API Voyage isoladamente:

```bash
PYTHONUNBUFFERED=1 python -c "
from config import verificar_voyage_api
r = verificar_voyage_api()
print('Embed:', '✅' if r['embed'] else '❌')
print('Rerank:', '✅' if r['rerank'] else '❌')
for e in r['erros']: print('  Erro:', e)
"
```

Deve mostrar:
```
Embed: ✅
Rerank: ✅
```

Se der erro, **PARE AQUI** e verifique:
- `VOYAGE_API_KEY` está correta no `.env`
- `VOYAGE_API_PROVIDER` está correto (atlas ou voyage)

---

## 8. Processamento dos PDFs {#8-processamento}

### 8.1. Teste com 1 PDF (5 minutos)

```bash
PYTHONUNBUFFERED=1 python processar_pdf.py "/Users/marcos.lopes/Documentos/DODF/DODF 001 02-01-2025 INTEGRA.pdf"
```

Saída esperada:
```
============================================================
  PROCESSANDO: DODF 001 02-01-2025 INTEGRA.pdf (0.8 MB)
  Embedding: voyage-4-large (1024d)
============================================================
        Salvando no GridFS... OK (0.8 MB)
        Extraindo texto de 48 paginas...
          [10/48] 10 uteis (45ms)
          [20/48] 20 uteis (38ms)
          [30/48] 30 uteis (42ms)
          [40/48] 40 uteis (39ms)
        Extracao OK: 2.1s — 47 uteis, 1 descartadas
        Criando chunks de 47 paginas...
        Chunks: 187 criados (12 descartados) em 0.4s
        Embeddings: 187 chunks em 8 lotes de 25
        [1/8] 25/187 (13%) [1.2s]
        [2/8] 50/187 (26%) [1.1s] | ETA: 7s
        ...
        ✅ Embeddings concluidos (8.7s API)
  ✅ 13s: 47 pgs, 187 chunks
============================================================
```

### 8.2. Processa todos os PDFs

```bash
# Usa monitor_pasta para processar TODOS os PDFs da pasta
PYTHONUNBUFFERED=1 python monitor_pasta.py
```

Vai processar todos os 123 PDFs sequencialmente. Estimativa: **30-60 minutos** (depende dos PDFs).
Quando terminar de processar todos, pressione Ctrl+C para parar o monitoramento.

> 💡 Se travar em um PDF específico, o registro fica como `status: erro` na coleção `pdfs` e o monitor continua para o próximo.

---

## 9. Iniciar a aplicação {#9-iniciar}

```bash
cd ~/Projetos/dodf-search && source venv/bin/activate
streamlit run chatbot.py
```

Acesse: http://localhost:8501

---

## 10. Testes finais {#10-testes}

### 10.1. Aba 🔍 Busca Textual
- Busque: **"Ibaneis Rocha"** → deve trazer dezenas de resultados com destaque
- Clique no link de qualquer PDF → deve abrir na página correta

### 10.2. Aba 💬 Chat (com IA) — Modo Rápido
- "**Quem é o governador do DF?**" → resposta em ~3s com fontes
- "**Bom dia**" → cumprimento

### 10.3. Aba 💬 Chat (com IA) — Modo Agente
- "**Quantos pedros foram nomeados em 2025?**" → deve chamar `consultar_atos` e retornar lista numerada com contagem

### 10.4. Aba 📤 Upload PDFs
- Arraste um PDF novo → clique "Processar PDFs" → acompanhe progresso
- Veja a lista de PDFs com status, páginas, chunks
- Clique "Abrir PDF" → deve abrir no navegador

### 10.5. Aba 📋 Auditoria
- Veja métricas (total, sessões, feedback)
- Filtre por modelo, status, feedback

---

## 11. Resolução de problemas {#11-troubleshooting}

### Travamento em "Extraindo texto..."
A versão atual já corrige isso (regex compilados, O(n)). Se voltar a travar:
```bash
# Diagnóstico
PYTHONUNBUFFERED=1 python processar_pdf.py --testar-limpeza /CAMINHO/PDF.pdf
```

### Erro "VOYAGE_API_KEY nao configurada"
- Edite o `.env` e cole a key sem aspas
- Verifique se o `.env` está em `~/Projetos/dodf-search/.env` (não em outro lugar)

### Erro 403 na Voyage API
- Confira se `VOYAGE_API_PROVIDER` está correto:
  - `atlas` se a key foi criada no MongoDB Atlas
  - `voyage` se foi criada no dash.voyageai.com

### Busca semântica retorna vazio
- Verifique se o índice `busca_vetorial` está com `numDimensions: 1024` no Atlas
- O índice deve estar em status "Active", não "Building"

### Links de PDF não abrem (404)
- Verifique se a porta 8502 está livre
- O servidor lê primeiro do GridFS, depois fallback para o disco
- Confirme que `PDF_FOLDER` aponta para o caminho correto

### "AttributeError: 'list' has no attribute 'lower'"
Já corrigido na versão atual (Gemini retorna lista — código converte automaticamente).

### Processamento muito lento
- Verifique sua conexão internet (Voyage API exige network)
- Cluster M0 do MongoDB tem limite de operações/seg — considere upgrade

---

## Resumo visual da arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│                       Streamlit (porta 8501)                     │
│  ┌──────────┬─────────────┬──────────────┬───────────────────┐  │
│  │ 💬 Chat  │ 🔍 Busca    │ 📤 Upload    │ 📋 Auditoria      │  │
│  └────┬─────┴──────┬──────┴──────┬───────┴──────┬────────────┘  │
└───────┼────────────┼─────────────┼──────────────┼───────────────┘
        │            │             │              │
        ▼            ▼             ▼              ▼
   ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌──────────┐
   │ Agente  │  │ Atlas   │  │ Processar│  │ MongoDB  │
   │ +10 fer.│  │ Search  │  │   PDF    │  │ stats    │
   └────┬────┘  └────┬────┘  └────┬─────┘  └────┬─────┘
        │            │            │             │
        ▼            ▼            ▼             ▼
   ┌─────────────────────────────────────────────────┐
   │            MongoDB Atlas (cloud)                 │
   │  documentos (chunks)  │  pdfs (metadados)        │
   │  GridFS (PDFs)        │  cache_semantico         │
   │  auditoria            │  metricas + feedback     │
   └─────────────────────────────────────────────────┘
                          ▲
                          │
                  ┌───────┴────────┐
                  │  Voyage 4 API  │
                  │  - embeddings  │
                  │  - rerank      │
                  └────────────────┘

┌─────────────────────────────────────────────┐
│ HTTP Server porta 8502 (le PDFs do GridFS)  │
└─────────────────────────────────────────────┘
```

---

## Resumo dos comandos (sequência completa)

```bash
# 1. Limpar
pkill -f streamlit
cd ~/Projetos/dodf-search && source venv/bin/activate
rm -f *.py && rm -rf static .streamlit __pycache__

# 2. Limpar MongoDB (rodar o script da seção 3.2)

# 3. Instalar arquivos novos
cp ~/Downloads/{config,setup_mongodb,processar_pdf,monitor_pasta,tools_dodf,chatbot}.py .
cp ~/Downloads/env.exemplo .env
nano .env  # editar com keys novas

# 4. Configurar índices no Atlas (web — seção 5)

# 5. Setup
python setup_mongodb.py

# 6. Testar Voyage
python -c "from config import verificar_voyage_api; print(verificar_voyage_api())"

# 7. Processar PDFs
PYTHONUNBUFFERED=1 python monitor_pasta.py
# Ctrl+C quando terminar todos

# 8. Iniciar
streamlit run chatbot.py
```
