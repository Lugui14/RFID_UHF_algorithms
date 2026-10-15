# Driver e Calculadora MRT para Leitor RFID UHF IN-R200

Este repositório contém a implementação do driver em Python para o leitor RFID UHF **IN-R200** (chipset **MagicRF M100**) e a calculadora de **Limiar Mínimo de Resposta (MRT / DMRT)** baseada no artigo científico _GreenTag_ (ACM TOSN 2025).

---

## ⚡ Pré-requisitos e Configuração Inicial

### 1. Dependências do Python

Certifique-se de ter o Python 3.8+ instalado com a biblioteca `pyserial`:

```bash
pip install pyserial
```

### 2. Permissões da Porta Serial (Linux)

Para conceder permissão de acesso à porta USB do leitor (`/dev/ttyUSB0`):

```bash
sudo chmod 666 /dev/ttyUSB0
# Ou adicione seu usuário ao grupo dialout (definitivo):
sudo usermod -aG dialout $USER
```

---

## 🚀 Como Usar

### 1. Execução do Experimento 7 (`main.py`)

Pipeline experimental automatizado para o **Experimento 7** (medição de **DMRT, MRT e RSSI** investigando a **invariância espacial e angular** sob **faixa única/constante de umidade do solo**):

```bash
# Verificar status das baterias do Experimento 7
python main.py --status

# Executar bateria 1 (Centro, rotação 0°) com 300 leituras (informando a umidade fixa aferida)
python main.py --bateria 1 --umidade 48.0

# Ou executar passando diretamente posição e rotação:
python main.py --posicao pos_esq --rotacao 90
```

- **Métricas:** Limiar Mínimo de Resposta da Tag Sensoriamento (MRT bruto e filtrado EMA), Limiar da Tag de Referência, Diferencial $\text{DMRT} = \text{MRT}_{\text{sens}} - \text{MRT}_{\text{ref}}$, e RSSI de ambas as tags.
- **Saídas:** CSV detalhado por leitura, painel gráfico de 3 eixos (PNG), tabela consolidada `experimento_7/consolidado_exp7.csv` e curvas analíticas.

---

### 2. Medição de MRT e DMRT (`mrt_calculator.py`)

Utilizado para determinar o limiar mínimo de potência RF necessário para energizar e ler uma tag (MRT), além de calcular a diferença relativa entre duas tags (DMRT).

```bash
python mrt_calculator.py
```

- **Funcionamento:**
  - **Varredura Linear (`linear_sweep_mrt`):** Varre a potência do leitor de 10.0 a 26.0 dBm (passo de 0.5 dBm), capturando o MRT bruto de cada tag presente.
  - **Busca Binária Rápida (`binary_search_mrt`):** Localiza o MRT exato de uma tag específica em complexidade $O(\log N)$ (Algoritmo 1 do GreenTag).
  - **Filtro Passa-Baixas EMA:** Aplica Média Móvel Exponencial ($y_i = \alpha x_i + (1 - \alpha) y_{i-1}$) para mitigar ruídos de canal RF.
  - **Cálculo de DMRT:** Calcula a diferença $\text{DMRT} = \text{MRT}_{\text{sensoriamento}} - \text{MRT}_{\text{referência}}$.

---

### 3. Mapeador de Novas Tags (`mapear_tags.py`)

Utilitário exclusivo para descobrir, identificar e registrar novas tags RFID UHF (individualmente ou em pares de Sensoriamento/Referência):

```bash
python mapear_tags.py
```

- **Menu Interativo:**
  - `1. Varredura em Tempo Real`: Monitora todas as tags no campo com barra visual de sinal RSSI e contagem. Ao parar, permite salvar qualquer tag detectada.
  - `2. Assistente Guiado de Pares`: Conduz passo a passo a identificação da **Tag de Sensoriamento** e da **Tag de Referência** (com opção de usar baixa potência RF para isolamento de tags próximas), salvando o setup e permitindo anexar diretamente em `anotacoes.md`.
  - `3. Mapear Tag Individual`: Atribui nome, papel e setup para qualquer tag aproximada da antena.
  - `4. Listar Tags Salvas`: Exibe o banco de dados em `tags_mapeadas.json`.
  - `5. Exportar para Markdown`: Gera blocos prontos para copiar e colar nos arquivos de experimentos.
- **Opções via linha de comando:**
  - `python mapear_tags.py --scan`: Executa diretamente a varredura ao vivo.
  - `python mapear_tags.py --pair`: Abre direto o assistente de par.
  - `python mapear_tags.py --list`: Lista o catálogo de tags e pares cadastrados.
  - `python mapear_tags.py --simulado`: Permite simular operações sem necessidade do leitor físico conectado.

---

## 📚 Documentação Detalhada

Para detalhes arquiteturais, especificações de protocolo binário e formulação matemática:

- 📖 [Documentação do Leitor e Protocolo Serial](documentacao_leitor_rfid.md)
- 📖 [Documentação da Calculadora MRT / DMRT](documentacao_calculadora_mrt.md)
