#!/usr/bin/env bash
# =============================================================================
# iniciar.sh — Inicia todos os servicos do DODF Search
# =============================================================================
# Pre-requisitos:
#   - Pasta do projeto: ~/Projetos/dodf-search
#   - venv ja criado
#   - .env configurado
#   - Ollama instalado (brew install ollama) — opcional para fallback local
#
# Uso:
#   ./iniciar.sh                    # inicia tudo
#   ./iniciar.sh --sem-ollama       # nao inicia Ollama
#   ./iniciar.sh --sem-monitor      # nao inicia monitor de pasta
#   ./iniciar.sh --parar            # para todos os servicos
#   ./iniciar.sh --status           # mostra status
# =============================================================================

set -e

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuracao
PROJETO_DIR="$HOME/Projetos/dodf-search"
LOG_DIR="$PROJETO_DIR/logs"
PID_DIR="$PROJETO_DIR/.pids"
STREAMLIT_PORT=8501
PDF_PORT=8502
OLLAMA_PORT=11434

# Flags
INICIAR_OLLAMA=true
INICIAR_MONTOR=true
ACAO="iniciar"

for arg in "$@"; do
    case $arg in
        --sem-ollama) INICIAR_OLLAMA=false ;;
        --sem-monitor) INICIAR_MONTOR=false ;;
        --parar) ACAO="parar" ;;
        --status) ACAO="status" ;;
        --help|-h)
            grep '^#' "$0" | head -20
            exit 0
            ;;
    esac
done

mkdir -p "$LOG_DIR" "$PID_DIR"

# =============================================================================
# FUNCOES
# =============================================================================

log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_ok()   { echo -e "${GREEN}✅ $1${NC}"; }
log_warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_err()  { echo -e "${RED}❌ $1${NC}"; }

# Verifica se servico esta rodando pela porta
porta_ativa() {
    lsof -ti:$1 > /dev/null 2>&1
}

# Verifica se PID file aponta para processo vivo
pid_vivo() {
    local pid_file=$1
    [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

# Mata processo via PID file
matar_processo() {
    local nome=$1
    local pid_file="$PID_DIR/$nome.pid"
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            sleep 1
            kill -9 "$pid" 2>/dev/null || true
            log_ok "$nome parado (PID $pid)"
        fi
        rm -f "$pid_file"
    fi
}

# =============================================================================
# VERIFICACOES DE PRE-REQUISITOS
# =============================================================================

verificar_prerequisitos() {
    log_info "Verificando pre-requisitos..."

    if [ ! -d "$PROJETO_DIR" ]; then
        log_err "Pasta do projeto nao encontrada: $PROJETO_DIR"
        exit 1
    fi
    cd "$PROJETO_DIR"

    if [ ! -d "venv" ]; then
        log_err "venv nao encontrado em $PROJETO_DIR/venv"
        log_info "Execute: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
        exit 1
    fi

    if [ ! -f ".env" ]; then
        log_err ".env nao encontrado em $PROJETO_DIR/.env"
        log_info "Copie env.exemplo para .env e configure suas chaves"
        exit 1
    fi

    if [ ! -f "chatbot.py" ]; then
        log_err "chatbot.py nao encontrado em $PROJETO_DIR"
        exit 1
    fi

    log_ok "Pre-requisitos OK"
}

# =============================================================================
# OLLAMA (LLM local — fallback)
# =============================================================================

iniciar_ollama() {
    if ! command -v ollama &> /dev/null; then
        log_warn "Ollama nao instalado. Pulando (Claude/Gemini ainda funcionam)"
        log_info "Para instalar: brew install ollama"
        return 0
    fi

    if porta_ativa $OLLAMA_PORT; then
        log_ok "Ollama ja rodando na porta $OLLAMA_PORT"
        return 0
    fi

    log_info "Iniciando Ollama..."
    nohup ollama serve > "$LOG_DIR/ollama.log" 2>&1 &
    echo $! > "$PID_DIR/ollama.pid"

    # Aguarda subir
    for i in {1..10}; do
        if porta_ativa $OLLAMA_PORT; then
            log_ok "Ollama iniciado (PID $(cat "$PID_DIR/ollama.pid"))"
            return 0
        fi
        sleep 1
    done
    log_err "Ollama nao subiu apos 10s. Veja $LOG_DIR/ollama.log"
    return 1
}

# =============================================================================
# MONITOR DE PASTA (auto-indexacao de novos PDFs)
# =============================================================================

iniciar_monitor() {
    if pid_vivo "$PID_DIR/monitor.pid"; then
        log_ok "Monitor de pasta ja rodando (PID $(cat "$PID_DIR/monitor.pid"))"
        return 0
    fi

    log_info "Iniciando monitor de pasta..."
    cd "$PROJETO_DIR"
    nohup bash -c "source venv/bin/activate && PYTHONUNBUFFERED=1 python monitor_pasta.py" \
        > "$LOG_DIR/monitor.log" 2>&1 &
    echo $! > "$PID_DIR/monitor.pid"
    sleep 2

    if pid_vivo "$PID_DIR/monitor.pid"; then
        log_ok "Monitor iniciado (PID $(cat "$PID_DIR/monitor.pid"))"
        log_info "  Log: tail -f $LOG_DIR/monitor.log"
    else
        log_err "Monitor falhou. Veja $LOG_DIR/monitor.log"
        return 1
    fi
}

# =============================================================================
# STREAMLIT (interface web)
# =============================================================================

iniciar_streamlit() {
    if porta_ativa $STREAMLIT_PORT; then
        log_warn "Porta $STREAMLIT_PORT ja em uso. Streamlit pode ja estar rodando."
        return 0
    fi

    log_info "Iniciando Streamlit..."
    cd "$PROJETO_DIR"
    nohup bash -c "source venv/bin/activate && streamlit run chatbot.py --server.port $STREAMLIT_PORT --server.headless true" \
        > "$LOG_DIR/streamlit.log" 2>&1 &
    echo $! > "$PID_DIR/streamlit.pid"

    # Aguarda subir
    for i in {1..15}; do
        if porta_ativa $STREAMLIT_PORT; then
            log_ok "Streamlit iniciado (PID $(cat "$PID_DIR/streamlit.pid"))"
            log_ok "Servidor PDF embutido na porta $PDF_PORT"
            return 0
        fi
        sleep 1
    done
    log_err "Streamlit nao subiu apos 15s. Veja $LOG_DIR/streamlit.log"
    return 1
}

# =============================================================================
# PARAR TUDO
# =============================================================================

parar_tudo() {
    log_info "Parando todos os servicos..."

    matar_processo "streamlit"
    matar_processo "monitor"
    matar_processo "ollama"

    # Garantia: mata qualquer streamlit/python residual nas portas
    for porta in $STREAMLIT_PORT $PDF_PORT; do
        local pid=$(lsof -ti:$porta 2>/dev/null || true)
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
            log_ok "Processo na porta $porta finalizado (PID $pid)"
        fi
    done

    log_ok "Todos os servicos parados"
}

# =============================================================================
# STATUS
# =============================================================================

mostrar_status() {
    echo ""
    echo "=============================================="
    echo "  STATUS DOS SERVICOS — DODF Search"
    echo "=============================================="

    # Ollama
    if porta_ativa $OLLAMA_PORT; then
        log_ok "Ollama:    rodando na porta $OLLAMA_PORT"
    else
        log_warn "Ollama:    parado"
    fi

    # Monitor
    if pid_vivo "$PID_DIR/monitor.pid"; then
        log_ok "Monitor:   rodando (PID $(cat "$PID_DIR/monitor.pid"))"
    else
        log_warn "Monitor:   parado"
    fi

    # Streamlit
    if porta_ativa $STREAMLIT_PORT; then
        log_ok "Streamlit: rodando em http://localhost:$STREAMLIT_PORT"
    else
        log_warn "Streamlit: parado"
    fi

    # PDF Server
    if porta_ativa $PDF_PORT; then
        log_ok "PDFs:      rodando na porta $PDF_PORT"
    else
        log_warn "PDFs:      parado (sobe junto com Streamlit)"
    fi

    echo ""
    echo "Logs em: $LOG_DIR"
    echo "PIDs em: $PID_DIR"
    echo ""
}

# =============================================================================
# MAIN
# =============================================================================

case $ACAO in
    parar)
        parar_tudo
        ;;
    status)
        mostrar_status
        ;;
    iniciar)
        echo ""
        echo "=============================================="
        echo "  🏛️  DODF Search — Inicializacao"
        echo "=============================================="
        echo ""

        verificar_prerequisitos

        if $INICIAR_OLLAMA; then
            iniciar_ollama
        else
            log_info "Ollama pulado (--sem-ollama)"
        fi

        if $INICIAR_MONTOR; then
            iniciar_monitor
        else
            log_info "Monitor pulado (--sem-monitor)"
        fi

        iniciar_streamlit

        echo ""
        echo "=============================================="
        log_ok "Sistema pronto!"
        echo "=============================================="
        echo ""
        echo "  💬 Chatbot:   http://localhost:$STREAMLIT_PORT"
        echo "  📄 PDFs:      http://localhost:$PDF_PORT"
        echo ""
        echo "Comandos uteis:"
        echo "  Ver status:        ./iniciar.sh --status"
        echo "  Parar tudo:        ./iniciar.sh --parar"
        echo "  Logs Streamlit:    tail -f $LOG_DIR/streamlit.log"
        echo "  Logs Monitor:      tail -f $LOG_DIR/monitor.log"
        echo ""
        ;;
esac
