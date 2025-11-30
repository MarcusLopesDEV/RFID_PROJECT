// Variáveis globais
let socket;

// Inicialização
document.addEventListener('DOMContentLoaded', function() {
    conectarWebSocket();
    carregarDados();
    
    // Atualizar a cada 3 segundos (fallback)
    setInterval(carregarDados, 3000);
});

// Conectar WebSocket
function conectarWebSocket() {
    socket = io();
    
    socket.on('connect', function() {
        console.log('Conectado ao servidor');
        atualizarStatus(true, 'Conectado');
        mostrarAlerta('Conectado ao servidor', 'success');
    });
    
    socket.on('disconnect', function() {
        console.log('Desconectado do servidor');
        atualizarStatus(false, 'Desconectado');
        mostrarAlerta('Desconectado do servidor', 'warning');
    });
    
    socket.on('dados_atualizados', function(data) {
        console.log('Dados atualizados recebidos');
        carregarDados();
        mostrarAlerta('Novo acesso detectado!', 'info');
    });
}

// Carregar dados da API
async function carregarDados() {
    try {
        const response = await fetch('/api/dados');
        const data = await response.json();
        
        atualizarEstatisticas(data.stats);
        atualizarTabelaAcessos(data.last_accesses);
        atualizarTabelaCartoes(data.cards);
        atualizarStatus(true, 'Conectado');
        
    } catch (error) {
        console.error('Erro ao carregar dados:', error);
        atualizarStatus(false, 'Erro de conexão');
    }
}

// Atualizar estatísticas
function atualizarEstatisticas(stats) {
    document.getElementById('totalCartoes').textContent = stats.total_cartoes;
    document.getElementById('totalAcessos').textContent = stats.total_acessos;
    document.getElementById('totalNegados').textContent = stats.total_suspeitos;
    document.getElementById('totalRepetidos').textContent = stats.total_repetidos;
}

// Função para mostrar detalhes do acesso
function mostrarDetalhesAcesso(acesso) {
    const localizacao = acesso.localizacao || {};
    const detalhes = `
        <div class="detalhes-acesso">
            <h6><i class="fas fa-info-circle me-2"></i>Detalhes do Acesso</h6>
            <hr>
            <p><strong>UID:</strong> <code>${acesso.uid}</code></p>
            <p><strong>Dispositivo:</strong> ${acesso.dispositivo}</p>
            <p><strong>Localização:</strong> ${localizacao.cidade || 'N/A'}, ${localizacao.regiao || 'N/A'}, ${localizacao.pais || 'N/A'}</p>
            <p><strong>IP:</strong> ${localizacao.ip || 'N/A'}</p>
            <p><strong>Provedor:</strong> ${localizacao.isp || 'N/A'}</p>
            <p><strong>Google Maps:</strong> <a href="${acesso.google_maps || '#'}" target="_blank" class="btn btn-sm btn-outline-primary">
                <i class="fas fa-map-marker-alt me-1"></i>Ver no mapa
            </a></p>
        </div>
    `;
    
    mostrarAlerta(detalhes, 'info');
}

// Atualizar tabela de acessos para incluir a localização
function atualizarTabelaAcessos(acessos) {
    const tbody = document.getElementById('tabelaAcessos');
    
    if (acessos.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted py-4">
                    Nenhum acesso registrado
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = acessos.map(acesso => `
        <tr onclick="mostrarDetalhesAcesso(${JSON.stringify(acesso).replace(/"/g, '&quot;')})" style="cursor: pointer;" class="hover-row">
            <td><code class="uid-code">${acesso.uid}</code></td>
            <td>${formatarData(acesso.timestamp)}</td>
            <td>
                <span class="status-badge ${acesso.resultado === 'Permitido' ? 'status-permitido' : acesso.resultado === 'Suspeito' ? 'status-suspeito' : 'status-negado'}">
                    <i class="fas ${acesso.resultado === 'Permitido' ? 'fa-check' : acesso.resultado === 'Suspeito' ? 'fa-exclamation-triangle' : 'fa-times'} me-1"></i>
                    ${acesso.resultado}
                </span>
            </td>
            <td>${acesso.dispositivo}</td>
            <td>${acesso.vezes_usado}</td>
        </tr>
    `).join('');
}

// Atualizar tabela de cartões
function atualizarTabelaCartoes(cartoes) {
    const tbody = document.getElementById('tabelaCartoes');
    const entries = Object.entries(cartoes);
    
    if (entries.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center text-muted py-4">
                    Nenhum cartão cadastrado
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = entries.map(([uid, info]) => `
        <tr>
            <td><code class="uid-code">${uid}</code></td>
            <td>${formatarData(info.primeiro_acesso)}</td>
            <td>${formatarData(info.ultimo_acesso)}</td>
            <td>${info.vezes_usado}</td>
            <td>${info.dispositivos_utilizados ? info.dispositivos_utilizados.join(', ') : 'N/A'}</td>
            <td>
                <span class="status-badge ${info.ultimo_resultado === 'Permitido' ? 'status-permitido' : info.ultimo_resultado === 'Suspeito' ? 'status-suspeito' : 'status-negado'}">
                    <i class="fas ${info.ultimo_resultado === 'Permitido' ? 'fa-check' : info.ultimo_resultado === 'Suspeito' ? 'fa-exclamation-triangle' : 'fa-times'} me-1"></i>
                    ${info.ultimo_resultado}
                </span>
            </td>
        </tr>
    `).join('');
}

// Atualizar status da conexão
function atualizarStatus(conectado, mensagem) {
    const icon = document.getElementById('statusIcon');
    const text = document.getElementById('statusText');
    
    if (conectado) {
        icon.className = 'fas fa-circle text-success me-1';
        text.textContent = mensagem || 'Conectado';
    } else {
        icon.className = 'fas fa-circle text-danger me-1';
        text.textContent = mensagem || 'Desconectado';
    }
}

// Mostrar alerta
function mostrarAlerta(mensagem, tipo) {
    const container = document.getElementById('alertContainer');
    const alert = document.createElement('div');
    alert.className = `alert alert-${tipo} alert-dismissible fade show`;
    alert.innerHTML = `
        ${mensagem}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    container.appendChild(alert);
    
    // Auto-remover após 8 segundos (mais tempo para detalhes)
    setTimeout(() => {
        if (alert.parentNode) {
            alert.remove();
        }
    }, 8000);
}

// Reiniciar conexão serial
async function reiniciarSerial() {
    try {
        const response = await fetch('/api/reiniciar_serial');
        const data = await response.json();
        mostrarAlerta(data.message, data.status === 'success' ? 'success' : 'danger');
    } catch (error) {
        mostrarAlerta('Erro ao reiniciar conexão serial', 'danger');
    }
}

// Formatadores
function formatarData(isoString) {
    if (!isoString || isoString === 'N/A') return 'N/A';
    
    try {
        const date = new Date(isoString);
        return date.toLocaleString('pt-BR');
    } catch (error) {
        return 'Data inválida';
    }
}

// Carregar status dos dispositivos
async function carregarStatusDispositivos() {
    try {
        const response = await fetch('/api/dispositivo/status');
        const data = await response.json();
        console.log('Status dos dispositivos:', data);
    } catch (error) {
        console.error('Erro ao carregar status:', error);
    }
}