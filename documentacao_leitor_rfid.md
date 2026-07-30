# Documentação do Leitor RFID UHF (IN-R200 / MagicRF M100)

## 1. Visão Geral e Contexto

Este documento detalha o funcionamento da integração, os protocolos de comunicação serial e a arquitetura do código desenvolvido para leitura de tags RFID UHF utilizando o leitor **IN-R200** (baseado no módulo/chipset **MagicRF M100**).

A comunicação com o leitor é realizada diretamente via porta serial USB (UART virtual através de chips como CP210x ou CH340), operando sob um protocolo de enquadramento binário nativo.

---

## 2. Detalhamento dos Protocolos de Comunicação

### 2.1. Configuração da Interface Serial (Camada Física)
- **Porta Padrão (Linux):** `/dev/ttyUSB0`
- **Baud Rate:** `115200 bps`
- **Data Bits:** `8`
- **Paridade:** `Nenhuma (None)`
- **Stop Bits:** `1`
- **Linhas de Controle:** `DTR = True`, `RTS = True` (necessários para habilitar e alimentar o conversor USB-Serial).

---

### 2.2. Protocolo de Enquadramento Binário (Binary Framing Protocol)

O leitor IN-R200 não opera via comandos AT textuais nem por stream ASCII simples. Toda mensagem trocada entre o Host (PC) e o Leitor (Reader) segue uma estrutura binária delimitada por **Bytes de Cabeçalho (Header)** e **Fim de Pacote (Ender)**.

#### Estrutura do Pacote de Dados (Frame Format)

| Campo | Tamanho | Descrição |
| :--- | :--- | :--- |
| **HEADER** | 1 Byte | Sempre `0xAA` (Indica o início do pacote) |
| **TYPE** | 1 Byte | `0x00` = Comando do Host<br>`0x01` = Resposta do Leitor<br>`0x02` = Notificação/Relatório do Leitor |
| **COMMAND** | 1 Byte | Código da operação (ex: `0x03`, `0xB6`, `0x27`, `0x28`) |
| **LENGTH** | 2 Bytes | Tamanho do campo Payload em bytes (Big-Endian) |
| **DATA PAYLOAD** | N Bytes | Dados do comando ou payload da tag lida |
| **CHECKSUM** | 1 Byte | Byte de validação LSB da soma de `TYPE + CMD + LEN + DATA` |
| **ENDER** | 1 Byte | Sempre `0xDD` (Indica o fim do pacote) |

#### Algoritmo de Cálculo do Checksum
O Checksum é calculado somando os bytes do payload interno (desconsiderando Header `0xAA` e Ender `0xDD`) e aplicando uma máscara de 8 bits (`mod 256`):

$$\text{Checksum} = \left( \sum_{i} \text{byte}_i \right) \ \& \ \text{0xFF}$$

---

### 2.3. Principais Comandos do Protocolo MagicRF M100

- **`0x03` (Get Module Hardware Info):** Solicita a versão de firmware/hardware do módulo.
- **`0xB6` (Set RF Power):** Configura a potência da antena em dBm (o valor é codificado em centésimos de dBm, por exemplo $26.0\text{ dBm} = 2600 = \text{0x0A28}$).
- **`0x27` (Read Multi-Tag / Inventory):** Inicia a varredura contínua de tags no campo de RF.
- **`0x28` (Stop Read):** Encerra a varredura contínua de tags.

---

### 2.4. Estrutura de Dados do Reporte de Tag RFID (Gen2 / ISO 18000-6C)

Quando uma tag RFID entra no campo de leitura durante o comando `0x27`, o leitor envia um pacote com `COMMAND = 0x22` ou `0x27`. O **DATA PAYLOAD** recebido possui a seguinte estrutura interna:

```
+---------------+-------------------+-----------------------------------+---------------+
| RSSI (1 Byte) | PC Word (2 Bytes) |      EPC Data (N Bytes / 96-bit)  | CRC (2 Bytes) |
+---------------+-------------------+-----------------------------------+---------------+
```

1. **RSSI (Received Signal Strength Indicator):** Nível de sinal recebido da tag.
2. **PC (Protocol Control):** 2 bytes indicando o tamanho do EPC e atributos de memória da tag Gen2 (ex: `3400`).
3. **EPC (Electronic Product Code):** Código único da tag (geralmente 12 bytes / 24 caracteres hexadecimais).
4. **CRC:** Checksum contido na própria tag para verificação de integridade EPC.

---

### 2.5. Comparativo: Binary Framing (IN-R200) vs. Protocolo LLRP (`teste.py`)

No repositório existem dois tipos de implementação:

- **`in_r200_driver.py` (Binary Framing Protocol):** Protocolo proprietário serial nativo para módulos leitores OEM integrados (MagicRF/IN-R200) conectados via UART/USB (`/dev/ttyUSB0`).
- **(LLRP - Low Level Reader Protocol):** Protocolo padronizado mundialmente pela EPCglobal para leitores de porte industrial/redes (como Impinj Speedway, Zebra FX9500), operando via **TCP/IP**.

---

## 3. Pormenores do Código Gerado

### 3.1. Arquitetura do Driver (`in_r200_driver.py`)

O arquivo `in_r200_driver.py` é um driver orientado a objetos encarregado da comunicação de baixo nível.

#### Funções Auxiliares de Enquadramento
- **`calc_checksum(hex_str: str) -> str`**: Recebe a sequência hexadecimal do pacote, realiza o somatório byte a byte e extrai os 8 bits menos significativos (LSB).
- **`build_frame(msg_type, cmd_code, data) -> bytes`**: Monta o pacote binário final formatado com Header `AA`, payload, checksum calculado e Ender `DD`.

#### Classe `INR200Reader`
- **`connect()`**: Abre a porta serial via `pyserial`, ativa as linhas de sinal `DTR` e `RTS` (fundamentais para alimentar adaptadores USB-Serial), limpa o buffer de entrada (`reset_input_buffer`) e valida a comunicação executando `get_module_info()`.
- **`set_rf_power(power_dbm)`**: Converte a potência desejada (ex: `26.0 dBm`) para hexadecimal e envia o comando `0xB6`.
- **Mecanismo de Watchdog e Multithreading (`start_inventory`)**:
  - Para não bloquear a aplicação principal, o driver dispara uma **Thread Daemon** em segundo plano (`_reader_loop`).
  - **Watchdog:** Como o comando `0x27` pode encerrar seu ciclo após determinado número de rodadas, a thread monitora o tempo decorrido desde o último pacote de tag lido (`last_cmd_sent`). Se transcorrer mais de 1,0 segundo sem dados, o comando de varredura é retransmitido automaticamente, garantindo leitura contínua ininterrupta.
  - **Filtro de Buffer:** Varre o buffer acumulador procurando por delimitações de `0xAA` até `0xDD`, valida a integridade do pacote e faz o slice exato dos campos `RSSI`, `PC` e `EPC`, repassando-os para a função de *callback*.

---

### 3.2. Arquitetura da Aplicação Principal (`main.py`)

O arquivo `main.py` serve como camada de aplicação e interface do usuário:

1. **Callback `on_tag_scanned(epc, rssi, pc)`**:
   - Mantém um dicionário global `scanned_tags` chaveado pelo EPC.
   - Trata novas descobertas (`NEW TAG DISCOVERED`) e atualizações de tags existentes (incrementando contador de leituras, atualizando timestamp e nível de sinal RSSI).
2. **Gerenciamento do Ciclo de Vida**:
   - Conecta ao leitor em `/dev/ttyUSB0`.
   - Ajusta a potência para `26.0 dBm`.
   - Inicia a leitura em background.
   - Aguarda o encerramento do programa via `Ctrl+C` (`KeyboardInterrupt`).
3. **Relatório Final (Summary Report)**:
   - Ao encerrar, interrompe a varredura (`stop_inventory`), fecha a porta serial (`close`) e exibe na tela um relatório com a quantidade total de tags únicas lidas, total de releituras, PC Word e nível RSSI.

---

## 4. Instruções de Execução

### Pré-requisitos
Certifique-se de que as permissões de acesso à porta serial no Linux estejam concedidas:

```bash
sudo chmod 666 /dev/ttyUSB0
# Ou adicione seu usuário ao grupo dialout:
sudo usermod -aG dialout $USER
```

### Executando a Aplicação
```bash
python main.py
```
