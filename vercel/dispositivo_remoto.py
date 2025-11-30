import requests
import time
import serial
from datetime import datetime
import json

# ===== CONFIGURAÇÕES =====
# ⚠️ AJUSTE ESTE IP PARA O IP DO SEU SERVIDOR CENTRAL ⚠️
SERVIDOR_CENTRAL = "http://192.168.1.100:5000"  # IP do servidor principal
DISPOSITIVO_ID = "DISPOSITIVO_REMOTO_01"
PORTA_ARDUINO = 'COM4'  # Ajuste para a porta do Arduino remoto
BAUDRATE = 9600

def obter_localizacao_aproximada():
    """Obtém localização aproximada do dispositivo remoto."""
    try:
        response = requests.get('https://api.ipify.org?format=json', timeout=5)
        ip_publico = response.json()['ip']
        
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

def enviar_para_servidor_central(uid, localizacao):
    """Envia dados de acesso para o servidor central."""
    try:
        dados = {
            'uid': uid,
            'dispositivo_id': DISPOSITIVO_ID,
            'localizacao': localizacao
        }
        
        response = requests.post(
            f"{SERVIDOR_CENTRAL}/api/dispositivo/registrar_acesso",
            json=dados,
            timeout=10
        )
        
        if response.status_code == 200:
            resultado = response.json()
            print(f"✅ Acesso registrado no servidor: {resultado}")
            return True
        else:
            print(f"❌ Erro ao registrar acesso: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Erro de comunicação com servidor: {e}")
        return False

def monitorar_arduino():
    """Monitora o Arduino local e envia dados para o servidor central."""
    arduino = None
    
    try:
        print(f"🔌 Conectando ao Arduino na porta {PORTA_ARDUINO}...")
        arduino = serial.Serial(PORTA_ARDUINO, BAUDRATE, timeout=2)
        time.sleep(2)
        
        print("✅ Arduino conectado")
        print("📡 Enviando dados para servidor central...")
        print("🔄 Monitorando cartões RFID...")
        
        while True:
            if arduino.in_waiting > 0:
                linha = arduino.readline().decode('utf-8', errors='ignore').strip()
                
                if linha and len(linha) >= 6:
                    # Ignorar mensagens de sistema
                    if any(palavra in linha.upper() for palavra in ['INICIADO', 'PRONTO', 'READY', 'SYSTEM', 'RFID']):
                        continue
                    
                    print(f"📨 Cartão detectado: {linha}")
                    
                    # Obter localização
                    localizacao = obter_localizacao_aproximada()
                    print(f"📍 Localização: {localizacao['cidade']}, {localizacao['regiao']}")
                    
                    # Enviar para servidor central
                    enviar_para_servidor_central(linha, localizacao)
            
            time.sleep(0.1)
            
    except Exception as e:
        print(f"❌ Erro: {e}")
    finally:
        if arduino:
            arduino.close()

if __name__ == '__main__':
    print("🚀 Dispositivo Remoto Iniciado")
    print(f"🆔 ID do Dispositivo: {DISPOSITIVO_ID}")
    print(f"📡 Servidor Central: {SERVIDOR_CENTRAL}")
    print("⚠️  Verifique se o IP do servidor central está correto!")
    print("⏳ Iniciando monitoramento...")
    
    # Instalar dependência: pip install requests pyserial
    
    monitorar_arduino()