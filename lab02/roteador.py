# -*- coding: utf-8 -*-

import csv
import json
import threading
import time
from argparse import ArgumentParser
import copy

import requests
from flask import Flask, jsonify, request

class Router:
    
    INFINITY = 16
    
    """
    Representa um roteador que executa o algoritmo de Vetor de Distância.
    """

    def __init__(self, my_address, neighbors, my_network, update_interval=1):
        """
        Inicializa o roteador.

        :param my_address: O endereço (ip:porta) deste roteador.
        :param neighbors: Um dicionário contendo os vizinhos diretos e o custo do link.
        Ex: {'127.0.0.1:5001': 5, '127.0.0.1:5002': 10}
        :param my_network: A rede que este roteador administra diretamente.
        Ex: '10.0.1.0/24'
        :param update_interval: O intervalo em segundos para enviar atualizações, o tempo que o roteador espera 
                                antes de enviar atualizações para os vizinhos.        """
        self.my_address = my_address
        self.neighbors = neighbors
        self.my_network = my_network
        self.update_interval = update_interval

        # TODO: Este é o local para criar e inicializar sua tabela de roteamento.
        # 1. Crie a estrutura de dados para a tabela de roteamento. Um dicionário é
        #    uma ótima escolha, onde as chaves são as redes de destino (ex: '10.0.1.0/24')
        #    e os valores são outro dicionário contendo 'cost' e 'next_hop'.
        #    Ex: {'10.0.1.0/24': {'cost': 0, 'next_hop': '10.0.1.0/24'}}
        
        self.routing_table = {}
        
        # 2. Adicione a rota para a rede que este roteador administra diretamente
        #    (a rede em 'self.my_network'). O custo para uma rede diretamente
        #    conectada é 0, e o 'next_hop' pode ser a própria rede ou o endereço do roteador.
        #
        
        self.routing_table[self.my_network] = {
            'cost':0,
            'next_hop': self.my_network
        }
        
        # 3. Adicione as rotas para seus vizinhos diretos, usando o dicionário
        #    'self.neighbors'. Para cada vizinho, o 'cost' é o custo do link direto
        #    e o 'next_hop' é o endereço do próprio vizinho.
        
        for vizinho, custo in self.neighbors.items():
             self.routing_table[vizinho] = {
                'cost':custo,
                'next_hop': vizinho
            }

        print("Tabela de roteamento inicial:")
        print(json.dumps(self.routing_table, indent=4))

        # Inicia o processo de atualização periódica em uma thread separada
        self._start_periodic_updates()

    def _start_periodic_updates(self):
        """Inicia uma thread para enviar atualizações periodicamente."""
        thread = threading.Thread(target=self._periodic_update_loop)
        thread.daemon = True
        thread.start()

    def _periodic_update_loop(self):
        """Loop que envia atualizações de roteamento em intervalos regulares."""
        while True:
            time.sleep(self.update_interval)
            print(f"[{time.ctime()}] Enviando atualizações periódicas para os vizinhos...")
            try:
                self.send_updates_to_neighbors()
            except Exception as e:
                print(f"Erro durante a atualização periódida: {e}")

    def ip_to_int(self, ip):
        a, b, c, d = map(int, ip.split('.'))
        return (a << 24) | (b << 16) | (c << 8) | d

    def int_to_ip(self, num):
        return ".".join([
            str((num >> 24) & 255),
            str((num >> 16) & 255),
            str((num >> 8) & 255),
            str(num & 255)
        ])

    def verifica_sumarizacao(self, net1, net2):
        ip1, prefix1 = net1.split('/')
        ip2, prefix2 = net2.split('/')
        
        prefix1 = int(prefix1)
        prefix2 = int(prefix2)

        # verifica máscaras
        if prefix1 != prefix2: return None

        #transforma ip em int
        ip1_int = self.ip_to_int(ip1)
        ip2_int = self.ip_to_int(ip2)

        bloco = 2 ** (32 - prefix1)

        # verifica se sao adjacentes
        if abs(ip1_int ^ ip2_int) != bloco: return None

        novo_prefixo = prefix1 - 1
        mask = (0xFFFFFFFF << (32 - novo_prefixo)) & 0xFFFFFFFF
        supernet_int = ip1_int & mask

        supernet_ip = self.int_to_ip(supernet_int)

        return f"{supernet_ip}/{novo_prefixo}"

    def summarize(self, tabela):
        redes = list(tabela.keys())
        removidas = set()

        for i in range(len(redes)):
            for j in range(i + 1, len(redes)):

                net1 = redes[i]
                net2 = redes[j]
                
                if '/' not in net1 or '/' not in net2:
                    continue

                if net1 in removidas or net2 in removidas:
                    continue
                

                info1 = tabela[net1]
                info2 = tabela[net2]

                # Regra principal: mesmo next_hop
                if info1['next_hop'] != info2['next_hop']:
                    continue

                supernet = self.verifica_sumarizacao(net1, net2)

                if supernet:
                    novo_custo = max(info1['cost'], info2['cost'])

                    tabela[supernet] = {
                        'cost': novo_custo,
                        'next_hop': info1['next_hop']
                    }

                    removidas.add(net1)
                    removidas.add(net2)

        for net in removidas:
            tabela.pop(net, None)

    def summarize_non_contiguous(self, tabela):
        grupos = {}
        nova_tabela = {}

        # 1. Separa as rotas sumarizáveis por next_hop
        for net, info in tabela.items():
            # Ignora chaves que não são redes CIDR (ex: '127.0.0.1:5001')
            if '/' not in net:
                nova_tabela[net] = info
                continue
                
            nh = info['next_hop']
            if nh not in grupos:
                grupos[nh] = []
            grupos[nh].append((net, info['cost']))

        # 2. Processa cada grupo encontrando o Maior Prefixo Comum (LCP)
        for nh, rotas in grupos.items():
            if len(rotas) == 1:
                # Se só tem uma rota para esse next_hop, mantém como está
                net, cost = rotas[0]
                nova_tabela[net] = {'cost': cost, 'next_hop': nh}
            else:
                ips_int = []
                max_cost = -1
                for net, cost in rotas:
                    ip_str, prefix_str = net.split('/')
                    ips_int.append(self.ip_to_int(ip_str))
                    # O custo da rota sumarizada deve ser o maior custo do grupo
                    if cost > max_cost:
                        max_cost = cost
                
                min_ip = min(ips_int)
                max_ip = max(ips_int)
                
                # XOR entre o menor e o maior IP para achar os bits diferentes
                diff = min_ip ^ max_ip
                
                # Conta quantos bits da direita para a esquerda precisam ser zerados (a máscara)
                shift = 0
                while diff > 0:
                    diff >>= 1
                    shift += 1
                
                # Calcula a nova máscara e o novo IP base
                novo_prefixo = 32 - shift
                
                if novo_prefixo < 8:
                  novo_prefixo = 8
    
                mask = (0xFFFFFFFF << shift) & 0xFFFFFFFF
                supernet_int = min_ip & mask
                supernet_ip = self.int_to_ip(supernet_int)
                
                nova_tabela[f"{supernet_ip}/{novo_prefixo}"] = {
                    'cost': max_cost,
                    'next_hop': nh
                }
        
        tabela.clear()
        tabela.update(nova_tabela)

    def send_updates_to_neighbors(self):
        """
        Envia a tabela de roteamento (potencialmente sumarizada) para todos os vizinhos.
        """
        # TODO: O código abaixo envia a tabela de roteamento *diretamente*.
        #
        # ESTE TRECHO DEVE SER CHAMAADO APOS A SUMARIZAÇÃO.
        #
        # dica:
        # 1. CRIE UMA CÓPIA da `self.routing_table` NÃO ALTERE ESTA VALOR.
        # 2. IMPLEMENTE A LÓGICA DE SUMARIZAÇÃO nesta cópia.
        # 3. ENVIE A CÓPIA SUMARIZADA no payload, em vez da tabela original.
        
        # Criação de cópia
        tabela_para_enviar = copy.deepcopy(self.routing_table) # ATENÇÃO: Substitua pela cópia sumarizada.

        # Sumarizando a cópia
        self.summarize(tabela_para_enviar)

        payload = {
            "sender_address": self.my_address,
            "routing_table": tabela_para_enviar
        }

        for neighbor_address in self.neighbors:
            url = f'http://{neighbor_address}/receive_update'
            try:
                print(f"Enviando tabela para {neighbor_address}")
                requests.post(url, json=payload, timeout=5)
            except requests.exceptions.RequestException as e:
                print(f"Não foi possível conectar ao vizinho {neighbor_address}. Erro: {e}")

# --- API Endpoints ---
# Instância do Flask e do Roteador (serão inicializadas no main)
app = Flask(__name__)
router_instance = None

@app.route('/routes', methods=['GET'])
def get_routes():
    """Endpoint para visualizar a tabela de roteamento atual."""
    # TODO: Aluno! Este endpoint está parcialmente implementado para ajudar na depuração.
    # Você pode mantê-lo como está ou customizá-lo se desejar.
    # - mantenha o routing_table como parte da resposta JSON.
    
    if router_instance:
        return jsonify({
            "vizinhos" : router_instance.neighbors,
            "my_network": router_instance.my_network,
            "my_address": router_instance.my_address,
            "update_interval": router_instance.update_interval,
            "routing_table": router_instance.routing_table 
        })
        
    return jsonify({"error": "Roteador não inicializado"}), 500

@app.route('/receive_update', methods=['POST'])
def receive_update():
    """Endpoint que recebe atualizações de roteamento de um vizinho."""
    if not request.json:
        return jsonify({"error": "Invalid request"}), 400

    update_data = request.json
    sender_address = update_data.get("sender_address")
    sender_table = update_data.get("routing_table")

    if not sender_address or not isinstance(sender_table, dict):
        return jsonify({"error": "Missing sender_address or routing_table"}), 400

    print(f"Recebida atualização de {sender_address}:")
    print(json.dumps(sender_table, indent=4))

    # TODO: Implemente a lógica de Bellman-Ford aqui.
    #
    # 1. Verifique se o remetente é um vizinho conhecido.
    
    if sender_address not in router_instance.neighbors:
        print(f'{sender_address} -> Não é vizinho direto')
        return jsonify({'status': 'ignored'}), 200
    
    # 2. Obtenha o custo do link direto para este vizinho a partir de `router_instance.neighbors`.
    
    custo_direto = router_instance.neighbors[sender_address]
    
    # 3. Itere sobre cada rota (`network`, `info`) na `sender_table` recebida.
    
    tabela_atualizada = False
    
    for network, info in sender_table.items():
        
    # 4. Calcule o novo custo para chegar à `network`:
    #    novo_custo = custo_do_link_direto + info['cost']
        
        if network == router_instance.my_address or network == router_instance.my_network:
            continue
          
        custo_vizinho = info['cost']
        novo_custo = custo_direto + custo_vizinho
        if novo_custo >= Router.INFINITY:
            novo_custo = Router.INFINITY
    # 5. Verifique sua própria tabela de roteamento:
    #    a. Se você não conhece a `network`, adicione-a à sua tabela com o
    #       `novo_custo` e o `next_hop` sendo o `sender_address`.
    
        if network not in router_instance.routing_table:
            
            router_instance.routing_table[network] = {
                'cost': novo_custo,
                'next_hop': sender_address
            }
            
            tabela_atualizada = True
            
    #    b. Se você já conhece a `network`, verifique se o `novo_custo` é menor
    #       que o custo que você já tem. Se for, atualize sua tabela com o
    #       novo custo e o novo `next_hop`.
    
        else: 
            rota_atual = router_instance.routing_table[network]
            cost_atual = rota_atual['cost']
            next_hop_atual = rota_atual['next_hop']
            
            if novo_custo < cost_atual:
                router_instance.routing_table[network] = {
                    'cost': novo_custo,
                    'next_hop': sender_address
                }
                
                tabela_atualizada = True
            
    #    c. (Opcional, mas importante para robustez): Se o `next_hop` para uma rota
    #       for o `sender_address`, você deve sempre atualizar o custo, mesmo que
    #       seja maior (isso ajuda a propagar notícias de links quebrados).
    
            elif next_hop_atual == sender_address:
                router_instance.routing_table[network]['cost'] = novo_custo
                tabela_atualizada = True
    #
    # 6. Mantenha um registro se sua tabela mudou ou não. Se mudou, talvez seja
    #    uma boa ideia imprimir a nova tabela no console.
    
    if tabela_atualizada:
        print("Tabela de roteamento Atualizada:")
        print(json.dumps(router_instance.routing_table, indent=4))

    return jsonify({"status": "success", "message": "Update received"}), 200

if __name__ == '__main__':
    parser = ArgumentParser(description="Simulador de Roteador com Vetor de Distância")
    parser.add_argument('-p', '--port', type=int, default=5000, help="Porta para executar o roteador.")
    parser.add_argument('-f', '--file', type=str, required=True, help="Arquivo CSV de configuração de vizinhos.")
    parser.add_argument('--network', type=str, required=True, help="Rede administrada por este roteador (ex: 10.0.1.0/24).")
    parser.add_argument('--interval', type=int, default=10, help="Intervalo de atualização periódica em segundos.")
    parser.add_argument('--address', type=str, required=True,
                    help="Endereço completo do roteador (ex: 192.168.51.121:5000)")
    args = parser.parse_args()

    # Leitura do arquivo de configuração de vizinhos
    neighbors_config = {}
    try:
        with open(args.file, mode='r') as infile:
            reader = csv.DictReader(infile)
            for row in reader:
                neighbors_config[row['vizinho']] = int(row['custo'])
    except FileNotFoundError:
        print(f"Erro: Arquivo de configuração '{args.file}' não encontrado.")
        exit(1)
    except (KeyError, ValueError) as e:
        print(f"Erro no formato do arquivo CSV: {e}. Verifique as colunas 'vizinho' e 'custo'.")
        exit(1)

    my_full_address = args.address
    print("--- Iniciando Roteador ---")
    print(f"Endereço: {my_full_address}")
    print(f"Rede Local: {args.network}")
    print(f"Vizinhos Diretos: {neighbors_config}")
    print(f"Intervalo de Atualização: {args.interval}s")
    print("--------------------------")

    router_instance = Router(
        my_address=my_full_address,
        neighbors=neighbors_config,
        my_network=args.network,
        update_interval=args.interval
    )

    # Inicia o servidor Flask
    app.run(host='0.0.0.0', port=args.port, debug=False)