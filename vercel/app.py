from flask import Flask, render_template, jsonify, send_from_directory, request
from flask_socketio import SocketIO, emit
import json
import serial
import time
import threading
from datetime import datetime
import os
import logging
import requests
from geopy.geocoders import Nominatim
import socket

# Configurar logging - apenas informações importantes
logging.basicConfig(level=logging.WARNING, format='%(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sistema_acesso_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# ===== CONFIGURAÇÕES =====
PORTA = 'COM4'  # Porta do Arduino LOCAL
BAUDRATE = 9600
TIMEOUT = 2
ARQUIVO_LOG = "log_acessos.json"

# Configurações do sistema distribuído
SISTEMA_ID = "SISTEMA_CENTRAL"  # Identificador único deste dispositivo
DISPOSITIVOS_AUTORIZADOS = ["SISTEMA_CENTRAL", "DISPOSITIVO_REMOTO_01"]  # IDs autorizados

# Dados em memória
dados_em_memoria = {
    "cards": {},
    "last_accesses": [],
    "stats": {
        "total_cartoes": 0,
        "total_acessos": 0,
        "total_suspeitos": 0,
        "total_repetidos": 0
    }
}

# Variáveis globais
arduino = None
serial_lock = threading.Lock()
ultimo_uid_processado = None
ultimo_tempo_processamento = 0
geolocator = Nominatim(user_agent="sistema_acesso")

# ===== FUNÇÕES DE GEOLOCALIZAÇÃO =====

def obter_localizacao_aproximada():
    """Obtém localização aproximada baseada no IP."""
    try:
        # Obter IP público
        response = requests.get('https://api.ipify.org?format=json', timeout=5)
        ip_publico = response.json()['ip']
        
        # Obter localização pelo IP
        response = requests.get(f'http://ip-api.com/json/{ip_publico}', timeout=5)
        dados_localizacao = response.json()
        
        if dados_localizacao['status'] == 'success':
            return {
                "ip": ip_publico,
                "cidade": dados_localizacao.get('city', 'Desconhecida'),
                "regiao": dados_localizacao.get('regionName', 'Desconhecida'),
                "pais": dados_localizacao.get('country', 'Desconhecido'),
                "lat": dados_localizacao.get('lat'),
                "lon": dados_localizacao.get('lon'),
                "isp": dados_localizacao.get('isp', 'Desconhecido')
            }
    except Exception as e:
        print(f"Erro ao obter localização: {e}")
    
    return {
        "ip": "Desconhecido",
        "cidade": "Desconhecida",
        "regiao": "Desconhecida",
        "pais": "Desconhecido",
        "lat": None,
        "lon": None,
        "isp": "Desconhecido"
    }

def obter_endereco_google_maps(lat, lon):
    """Obtém endereço formatado para Google Maps."""
    if lat and lon:
        return f"https://www.google.com/maps?q={lat},{lon}"
    return "Localização não disponível"

# ===== FUNÇÕES PRINCIPAIS =====

def carregar_log():
    """Carrega o arquivo JSON de log."""
    try:
        if not os.path.exists(ARQUIVO_LOG):
            with open(ARQUIVO_LOG, 'w', encoding='utf-8') as f:
                json.dump({}, f, indent=4)
            return {}
        
        with open(ARQUIVO_LOG, 'r', encoding='utf-8') as f:
            conteudo = f.read().strip()
            if not conteudo:
                return {}
            return json.loads(conteudo)
    except Exception as e:
        print(f"Erro ao carregar log: {e}")
        return {}

def salvar_log(data):
    """Salva dados no arquivo JSON."""
    try:
        with open(ARQUIVO_LOG, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Erro ao salvar log: {e}")
        return False

def inicializar_serial():
    """Inicializa a conexão serial."""
    global arduino
    try:
        # Fechar conexão existente
        if arduino is not None:
            try:
                arduino.close()
            except:
                pass
            time.sleep(1)
            
        print(f"Conectando na porta {PORTA}...")
        arduino = serial.Serial(
            port=PORTA,
            baudrate=BAUDRATE,
            timeout=TIMEOUT,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            rtscts=False,
            dsrdtr=False
        )
        
        # Aguardar Arduino inicializar
        time.sleep(2)
        
        # Limpar buffer completamente
        if arduino.in_waiting > 0:
            arduino.read(arduino.in_waiting)
            
        print("✅ Conexão serial estabelecida")
        return True
        
    except Exception as e:
        print(f"❌ Erro na conexão serial: {e}")
        arduino = None
        return False

def notificar_clientes():
    """Notifica todos os clientes web sobre atualização."""
    try:
        socketio.emit('dados_atualizados', {
            'message': 'Novos dados disponíveis',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        print(f"Erro ao notificar clientes: {e}")

def enviar_resposta_arduino(comando):
    """Envia resposta para Arduino."""
    global arduino
    with serial_lock:
        if arduino is not None and hasattr(arduino, 'is_open') and arduino.is_open:
            try:
                arduino.write(comando)
                arduino.flush()
                return True
            except Exception as e:
                print(f"Erro ao enviar comando: {e}")
                arduino = None
                return False
        else:
            print("⚠️ Arduino não disponível para envio")
            return False

def verificar_acesso_suspeito(uid, dispositivo_atual, log_data):
    """Verifica se o acesso é suspeito (cartão usado em dispositivo diferente)."""
    if uid in log_data:
        # Verificar se a chave 'acessos' existe
        acessos_anteriores = log_data[uid].get("acessos", [])
        
        # Se não há acessos anteriores, não é suspeito
        if not acessos_anteriores:
            return False
            
        for acesso in acessos_anteriores[-5:]:  # Verificar últimos 5 acessos
            if acesso.get("dispositivo") != dispositivo_atual:
                return True
                
    return False

def processar_uid(uid, dispositivo_id=SISTEMA_ID, localizacao=None):
    """Processa um UID recebido do Arduino ou de dispositivo remoto."""
    global ultimo_uid_processado, ultimo_tempo_processamento
    
    try:
        # Prevenir processamento duplicado rápido
        tempo_atual = time.time()
        if uid == ultimo_uid_processado and tempo_atual - ultimo_tempo_processamento < 3:
            return False
            
        ultimo_uid_processado = uid
        ultimo_tempo_processamento = tempo_atual
        
        print(f"Cartão detectado: {uid} no dispositivo: {dispositivo_id}")
        
        # Carregar log atual
        log_data = carregar_log()
        agora = datetime.now().isoformat()
        
        # Obter localização se não for fornecida
        if not localizacao:
            localizacao = obter_localizacao_aproximada()
        
        # Verificar se é suspeito (cartão usado em outro dispositivo)
        suspeito = verificar_acesso_suspeito(uid, dispositivo_id, log_data)
        
        # Determinar resultado
        if suspeito:
            resultado = "Suspeito"
            mensagem = f"🚨 ACESSO SUSPEITO - Cartão usado em dispositivo diferente"
            comando = b'SUSPECT\n'
        else:
            resultado = "Permitido"
            mensagem = "✅ Acesso PERMITIDO"
            comando = b'OK\n'
        
        print(mensagem)
        
        # Preparar dados do acesso
        dados_acesso = {
            "timestamp": agora,
            "dispositivo": dispositivo_id,
            "resultado": resultado,
            "localizacao": localizacao,
            "google_maps": obter_endereco_google_maps(localizacao.get('lat'), localizacao.get('lon'))
        }
        
        # Atualizar dados - INICIALIZAR ESTRUTURA CORRETAMENTE
        if uid not in log_data:
            # Primeiro acesso - criar estrutura completa
            log_data[uid] = {
                "primeiro_acesso": agora,
                "ultimo_acesso": agora,
                "vezes_usado": 1,
                "acessos": [dados_acesso],
                "dispositivos_utilizados": [dispositivo_id]
            }
        else:
            # Acesso subsequente - garantir que todas as chaves existam
            log_data[uid]["ultimo_acesso"] = agora
            log_data[uid]["vezes_usado"] = log_data[uid].get("vezes_usado", 0) + 1
            
            # Garantir que 'acessos' existe
            if "acessos" not in log_data[uid]:
                log_data[uid]["acessos"] = []
            log_data[uid]["acessos"].append(dados_acesso)
            
            # Garantir que 'dispositivos_utilizados' existe
            if "dispositivos_utilizados" not in log_data[uid]:
                log_data[uid]["dispositivos_utilizados"] = []
            
            # Atualizar lista de dispositivos únicos
            if dispositivo_id not in log_data[uid]["dispositivos_utilizados"]:
                log_data[uid]["dispositivos_utilizados"].append(dispositivo_id)
        
        # Salvar no arquivo
        if salvar_log(log_data):
            print("Dados salvos no JSON")
        else:
            print("Erro ao salvar dados")
        
        # Enviar resposta para Arduino (apenas se for dispositivo local)
        if dispositivo_id == SISTEMA_ID:
            enviar_resposta_arduino(comando)
        
        # Atualizar dados em memória e notificar clientes
        atualizar_dados_interface()
        notificar_clientes()
        
        return True
        
    except Exception as e:
        print(f"Erro ao processar UID: {e}")
        return False

def extrair_uid(dados):
    """Extrai UID dos dados."""
    try:
        dados = dados.strip()
        
        # Remover caracteres especiais
        dados_limpos = ''.join(c for c in dados if c.isalnum() or c in ['_', '-'])
        
        # Verificar se é um UID válido
        if len(dados_limpos) >= 6 and dados_limpos.isalnum():
            return dados_limpos
        
        return None
        
    except Exception:
        return None

def atualizar_dados_interface():
    """Atualiza os dados em memória para a interface web."""
    try:
        log_data = carregar_log()
        
        cartoes = {}
        ultimos_acessos = []
        
        for uid, info in log_data.items():
            # Garantir que todas as chaves existam
            primeiro_acesso = info.get("primeiro_acesso", info.get("ultimo_acesso", "N/A"))
            ultimo_acesso = info.get("ultimo_acesso", "N/A")
            vezes_usado = info.get("vezes_usado", 0)
            dispositivos_utilizados = info.get("dispositivos_utilizados", [])
            acessos = info.get("acessos", [])
            
            cartoes[uid] = {
                "primeiro_acesso": primeiro_acesso,
                "ultimo_acesso": ultimo_acesso,
                "vezes_usado": vezes_usado,
                "dispositivos_utilizados": dispositivos_utilizados,
                "ultimo_resultado": acessos[-1].get("resultado", "N/A") if acessos else "N/A"
            }
            
            # Processar últimos acessos
            for acesso in acessos[-5:]:  # Últimos 5 acessos
                ultimos_acessos.append({
                    "uid": uid,
                    "timestamp": acesso.get("timestamp", "N/A"),
                    "resultado": acesso.get("resultado", "N/A"),
                    "dispositivo": acesso.get("dispositivo", "N/A"),
                    "localizacao": acesso.get("localizacao", {}),
                    "google_maps": acesso.get("google_maps", "#"),
                    "vezes_usado": vezes_usado
                })
        
        # Ordenar por data mais recente
        ultimos_acessos.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Calcular estatísticas
        total_cartoes = len(cartoes)
        total_acessos = sum(info["vezes_usado"] for info in cartoes.values())
        total_suspeitos = sum(1 for info in cartoes.values() if len(info.get("dispositivos_utilizados", [])) > 1)
        total_repetidos = sum(1 for info in cartoes.values() if info["vezes_usado"] > 1)
        
        # Atualizar memória
        dados_em_memoria["cards"] = cartoes
        dados_em_memoria["last_accesses"] = ultimos_acessos[:10]
        dados_em_memoria["stats"] = {
            "total_cartoes": total_cartoes,
            "total_acessos": total_acessos,
            "total_suspeitos": total_suspeitos,
            "total_repetidos": total_repetidos
        }
        
    except Exception as e:
        print(f"Erro ao atualizar interface: {e}")

def monitor_serial():
    """Thread para monitorar a porta serial."""
    global arduino
    
    while True:
        try:
            # Reconectar se necessário
            if arduino is None or not hasattr(arduino, 'is_open') or not arduino.is_open:
                print("Tentando reconectar Arduino...")
                if not inicializar_serial():
                    time.sleep(3)
                    continue
            
            # Ler dados
            with serial_lock:
                if arduino is not None and arduino.is_open:
                    try:
                        if arduino.in_waiting > 0:
                            linha = arduino.readline().decode('utf-8', errors='ignore').strip()
                            
                            if linha:
                                # Ignorar mensagens de sistema
                                if any(palavra in linha.upper() for palavra in ['INICIADO', 'PRONTO', 'READY', 'SYSTEM', 'RFID']):
                                    continue
                                
                                # Tentar extrair UID
                                uid = extrair_uid(linha)
                                
                                if uid:
                                    # Processar em thread separada
                                    threading.Thread(target=processar_uid, args=(uid,), daemon=True).start()
                            
                    except Exception as e:
                        print(f"Erro na leitura serial: {e}")
                        arduino = None
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Erro geral na thread serial: {e}")
            arduino = None
            time.sleep(2)

# ===== ROTAS FLASK =====

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/dados')
def api_dados():
    return jsonify(dados_em_memoria)

@app.route('/api/atualizar')
def api_atualizar():
    atualizar_dados_interface()
    return jsonify({"status": "success", "message": "Dados atualizados"})

@app.route('/api/status')
def api_status():
    status_serial = "conectado" if arduino is not None and arduino.is_open else "desconectado"
    return jsonify({
        "serial_status": status_serial,
        "cartoes_cadastrados": len(dados_em_memoria["cards"]),
        "sistema_id": SISTEMA_ID
    })

@app.route('/api/reiniciar_serial')
def api_reiniciar_serial():
    """Rota para reiniciar a conexão serial."""
    global arduino
    try:
        if arduino is not None:
            try:
                arduino.close()
            except:
                pass
        arduino = None
        time.sleep(1)
        sucesso = inicializar_serial()
        return jsonify({
            "status": "success" if sucesso else "error", 
            "message": "Conexão serial reiniciada"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ===== API PARA DISPOSITIVOS REMOTOS =====

@app.route('/api/dispositivo/registrar_acesso', methods=['POST'])
def registrar_acesso_remoto():
    """API para dispositivos remotos registrarem acessos."""
    try:
        dados = request.get_json()
        
        if not dados:
            return jsonify({"status": "error", "message": "Dados não fornecidos"}), 400
        
        uid = dados.get('uid')
        dispositivo_id = dados.get('dispositivo_id')
        localizacao = dados.get('localizacao')
        
        if not uid or not dispositivo_id:
            return jsonify({"status": "error", "message": "UID e dispositivo_id são obrigatórios"}), 400
        
        # Verificar se dispositivo é autorizado
        if dispositivo_id not in DISPOSITIVOS_AUTORIZADOS:
            return jsonify({"status": "error", "message": "Dispositivo não autorizado"}), 403
        
        # Processar o acesso
        sucesso = processar_uid(uid, dispositivo_id, localizacao)
        
        if sucesso:
            return jsonify({"status": "success", "message": "Acesso registrado"})
        else:
            return jsonify({"status": "error", "message": "Erro ao processar acesso"})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/dispositivo/status')
def status_dispositivos():
    """Retorna status dos dispositivos do sistema."""
    log_data = carregar_log()
    
    dispositivos = {}
    for uid, info in log_data.items():
        for acesso in info.get("acessos", []):
            dispositivo = acesso.get("dispositivo")
            if dispositivo not in dispositivos:
                dispositivos[dispositivo] = {
                    "total_acessos": 0,
                    "ultimo_acesso": None,
                    "acessos_suspeitos": 0
                }
            
            dispositivos[dispositivo]["total_acessos"] += 1
            
            if acesso.get("resultado") == "Suspeito":
                dispositivos[dispositivo]["acessos_suspeitos"] += 1
            
            # Atualizar último acesso
            if not dispositivos[dispositivo]["ultimo_acesso"] or acesso["timestamp"] > dispositivos[dispositivo]["ultimo_acesso"]:
                dispositivos[dispositivo]["ultimo_acesso"] = acesso["timestamp"]
    
    return jsonify({"dispositivos": dispositivos})

# ===== SERVIÇO DE ARQUIVOS ESTÁTICOS =====

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve arquivos estáticos (CSS, JS, imagens)."""
    return send_from_directory('static', filename)

# ===== WEB SOCKETS =====

@socketio.on('connect')
def handle_connect():
    emit('conexao_estabelecida', {'message': 'Conectado ao servidor'})

@socketio.on('disconnect')
def handle_disconnect():
    pass

@socketio.on('solicitar_dados')
def handle_solicitar_dados():
    emit('dados_atualizados', {'message': 'Dados enviados'})

# ===== INICIALIZAÇÃO =====

if __name__ == '__main__':
    # Instalar dependências: pip install geopy requests flask-socketio
    
    # Criar arquivo de log se não existir
    if not os.path.exists(ARQUIVO_LOG):
        with open(ARQUIVO_LOG, 'w') as f:
            json.dump({}, f, indent=4)
        print("Arquivo de log criado")
    
    # Carregar dados iniciais
    atualizar_dados_interface()
    
    # Iniciar thread serial
    serial_thread = threading.Thread(target=monitor_serial, daemon=True)
    serial_thread.start()
    
    print("🚀 Servidor Central iniciado em http://localhost:5000")
    print("📊 Interface web disponível")
    print("🔌 Monitorando cartões RFID...")
    print("🌍 Sistema de geolocalização ativo")
    print("📡 API para dispositivos remotos disponível")
    print(f"🆔 ID do Sistema: {SISTEMA_ID}")
    print("📍 Acesse: http://localhost:5000 para ver a interface")
    
    # Usar socketio.run em vez de app.run
    socketio.run(app, debug=False, host='0.0.0.0', port=5000, use_reloader=False)