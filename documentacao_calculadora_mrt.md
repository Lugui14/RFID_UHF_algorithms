# Documentação da Calculadora MRT e DMRT (GreenTag / IN-R200)

## 1. Visão Geral e Conceitos Teóricos

Esta documentação descreve a implementação da **Calculadora de Limiar Mínimo de Resposta (Minimum Response Threshold - MRT)** e **MRT Diferencial (DMRT)** contida em `mrt_calculator.py`.

A ferramenta foi projetada com base nas formulações teóricas e algoritmos do artigo científico **GreenTag (ACM TOSN 2025 / DOI: 3715128.pdf)**, integrado diretamente ao driver nativo do leitor **IN-R200 (MagicRF M100)**.

---

### 1.1. O que é MRT (Minimum Response Threshold)?
O **MRT** é a **menor potência de transmissão do leitor (em dBm)** necessária para energizar o circuito integrado (CI) de uma tag RFID passiva e fazê-la responder com o seu código EPC no campo de RF.
- Se a potência transmitida for menor que o MRT, a tag não acumula energia suficiente e permanece inativa.
- O valor do MRT varia de acordo com a distância, orientação da antena, atenuação do meio e propriedades dielétricas do ambiente (ex: presença de umidade ou materiais sensores).

### 1.2. O que é DMRT (Differential Minimum Response Threshold)?
O **DMRT** é a métrica diferencial entre duas tags estrategicamente posicionadas (uma tag de sensoriamento na parte inferior e uma tag de referência na parte superior):

$$\text{DMRT} = \text{MRT}_{\text{sensoriamento}} - \text{MRT}_{\text{referência}}$$

O uso do DMRT cancela interferências ambientais comuns e variações de distância, isolando as mudanças causadas unicamente pela grandeza física sendo medida pelo sensor.

---

## 2. Algoritmos Implementados

O arquivo `mrt_calculator.py` implementa três algoritmos principais:

### 2.1. Varredura Linear de Potência (`linear_sweep_mrt`)
Varre sequencialmente a potência do leitor a partir de `min_power` até `max_power` com incrementos discretos `power_step`.

1. Ajusta a potência RF do leitor para $P_{\text{atual}}$.
2. Executa a varredura por um tempo de permanência (`dwell_time`, ex: 0,4 segundos).
3. A primeira potência na qual cada EPC é detectado é registrada como seu **Raw MRT**.

### 2.2. Busca Binária Rápida de MRT (`binary_search_mrt`)
Implementação direta do **Algoritmo 1 do artigo GreenTag**, reduzindo o tempo de medição de $O(N)$ para $O(\log N)$ para uma tag alvo específica:

1. **Validação:** Testa a potência máxima (`max_power`). Se a tag não for detectada, interrompe a busca.
2. **Divisão Binária:** Ajusta a potência para a metade da faixa ($\text{mid} = \frac{\text{low} + \text{high}}{2}$), arredondando para o grid do `power_step`.
3. **Verificação de Limiar:**
   - Se a tag responde em `mid`, testa se ela deixa de responder em `mid - power_step`. Em caso afirmativo, `mid` é o MRT exato. Se continuar respondendo, busca na metade inferior (`high = mid - power_step`).
   - Se a tag não responde em `mid`, busca na metade superior (`low = mid + power_step`).

### 2.3. Filtro Passa-Baixas / Suavização Temporal (`apply_low_pass_filter`)
Para atenuar ruídos de desvanecimento multicaminho (fading) e flutuações de canal RF, é aplicado um filtro de **Média Móvel Exponencial (EMA)** (Equação 11 do artigo GreenTag):

$$y_i = \alpha \cdot x_i + (1 - \alpha) \cdot y_{i-1}$$

- $x_i$: Valor instantâneo do MRT medido no ciclo atual.
- $y_{i-1}$: Valor filtrado acumulado dos ciclos anteriores.
- $\alpha$: Fator de suavização (padrão $\alpha = 0,2$).

---

## 3. Pormenores do Código Gerado (`mrt_calculator.py`)

### 3.1. Estrutura da Classe `MRTCalculator`

```python
class MRTCalculator:
    def __init__(
        self,
        reader: INR200Reader,
        min_power: float = 10.0,
        max_power: float = 26.0,
        power_step: float = 0.5,
        dwell_time: float = 0.4
    ):
        ...
```

#### Parâmetros do Construtor:
- `reader`: Instância conectada do driver `INR200Reader`.
- `min_power`: Potência mínima a ser testada em dBm (Padrão: `10.0 dBm`).
- `max_power`: Potência máxima a ser testada em dBm (Padrão: `26.0 dBm`).
- `power_step`: Resolução/passo da potência em dBm (Padrão: `0.5 dBm`).
- `dwell_time`: Tempo em segundos de permanência da leitura em cada nível de potência (Padrão: `0.4 s`).

---

### 3.2. Métodos da Classe

#### 1. `test_tag_read(power_dbm, target_epc)`
Ajusta a potência RF via `reader.set_rf_power(power_dbm)`, ativa a varredura contínua com `start_inventory()`, aguarda `dwell_time` segundos e interrompe com `stop_inventory()`. Retorna as tags detectadas e suas respectivas estatísticas (`RSSI`, `PC`).

#### 2. `linear_sweep_mrt()`
Executa a varredura linear em toda a faixa de potências e mapeia cada `EPC -> Raw MRT`.

#### 3. `binary_search_mrt(target_epc)`
Busca binária rápida para identificar com precisão o MRT de uma tag alvo específica.

#### 4. `apply_low_pass_filter(epc, raw_mrt, alpha=0.2)`
Aplica o filtro passa-baixas EMA para suavizar a leitura do MRT de determinada tag.

#### 5. `calculate_dmrt(sensing_mrt, reference_mrt)` [Método Estático]
Calcula a diferença $\text{DMRT} = \text{MRT}_{\text{sensoriamento}} - \text{MRT}_{\text{referência}}$.

---

### 3.3. Aplicação Principal e Fluxo de Execução (`main()`)

O bloco principal do script realiza as seguintes etapas:

1. **Conexão:** Abre a porta serial `/dev/ttyUSB0` a 115200 baud.
2. **Instanciação:** Configura a calculadora com potências de 10.0 a 26.0 dBm (passo 0.5 dBm).
3. **Varredura:** Executa a varredura linear para detectar todas as tags presentes.
4. **Filtragem:** Suaviza as medições brutas através do filtro EMA passa-baixas.
5. **Cálculo de DMRT:** Caso ao menos duas tags sejam identificadas, calcula automaticamente o DMRT entre a tag de sensoriamento e a tag de referência.
6. **Restauração:** Restaura a potência original do leitor para `26.0 dBm` e encerra a conexão serial em um bloco `finally`.

---

## 4. Como Executar

```bash
# Garantir permissão na porta serial USB:
sudo chmod 666 /dev/ttyUSB0

# Executar o script da calculadora MRT:
python mrt_calculator.py
```

### Exemplo de Saída no Terminal:

```text
=================================================================
  IN-R200 Minimum Response Threshold (MRT) & DMRT Measurement
=================================================================
✅ Connected to IN-R200 Reader on /dev/ttyUSB0

🔍 Starting Linear Power Sweep (10.0 dBm to 26.0 dBm, step 0.5 dBm)...
  🎯 [MRT FOUND] EPC: E200470FF3306026244B0112 -> MRT = 14.5 dBm
  🎯 [MRT FOUND] EPC: E200470FF3306026244B0115 -> MRT = 16.0 dBm

=================================================================
                   MRT SCAN RESULTS
=================================================================
 🏷️  EPC: E200470FF3306026244B0112 | Raw MRT: 14.5 dBm | Filtered MRT: 14.50 dBm
 🏷️  EPC: E200470FF3306026244B0115 | Raw MRT: 16.0 dBm | Filtered MRT: 16.00 dBm
=================================================================

📊 Differential MRT (DMRT) Calculation:
   - Sensing Tag  (Bottom) EPC: E200470FF3306026244B0112 | Filtered MRT: 14.50 dBm
   - Reference Tag (Top)   EPC: E200470FF3306026244B0115 | Filtered MRT: 16.00 dBm
   👉 Calculated DMRT: -1.50 dB
```
