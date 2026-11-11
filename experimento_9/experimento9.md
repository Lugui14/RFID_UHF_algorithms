# Experimento 9 - Medições de DMRT em Vaso com Sensor RainPoint e Associação de Ground Truth Gravimétrico (Antena 55 cm Acima)

## 1. Visão Geral

O **Experimento 9** possui um setup semelhante ao do **Experimento 6** (vaso de planta em ambiente laboratorial com antena fixada a **55 cm de altura** acima do vaso), agora empregando o par diferencial de tags RFID UHF (**Sensoriamento** e **Referência**) para medir a métrica **DMRT** ($\text{DMRT} = \text{MRT}_{\text{sens}} - \text{MRT}_{\text{ref}}$), além do **MRT** e do **RSSI** de ambas as tags.

Neste experimento:

1. São realizadas entre **7 e 12 medições** da métrica **DMRT** em vasos em ambiente laboratorial, cobrindo diferentes níveis de umidade do solo (desde o solo seco inicial até próximo da saturação).
2. No momento de cada medição, registra-se o **valor de umidade medido pelo sensor comercial capacitivo RainPoint** (`--umidade`).
3. Posteriormente, após a realização das **análises gravimétricas laboratoriais** (cujo valor percentual de umidade é calculado externamente), o valor de **Ground Truth** é associado a cada uma das medições realizadas (`--groundtruth` ou `--groundtruth-list`), estabelecendo o mapeamento triplo:
   $$\overline{\text{DMRT}}\ (\text{dB}) \;\longleftrightarrow\; \text{Umidade RainPoint}\ (\%) \;\longleftrightarrow\; \text{Umidade Ground Truth Gravimétrico}\ (\%)$$

---

## 2. Setup do Experimento

1. **Tag de Sensoriamento:** `E2806995000050136FD13575`
2. **Tag de Referência:** `E2806995000050136FD13975`
3. **Posição da Antena:** 55 cm de distância vertical acima da superfície do vaso (visada superior vertical).
4. **Substrato:** Vaso(s) de planta com substrato em ambiente laboratorial.
5. **Instrumento Comercial Comparativo:** Sensor capacitivo de umidade do solo **RainPoint**.
6. **Referência Padrão (_Ground Truth_):** Umidade obtida por análise gravimétrica laboratorial (calculada externamente e associada ao final às medições).
7. **Hardware de Leitura:** Leitor RFID UHF **IN-R200 (MagicRF M100)** conectado via USB (`/dev/ttyUSB0`) operando a 115200 baud.
8. **Faixa de Potência RF:** 15.0 dBm a 26.0 dBm (passo de 1.0 dBm, com parada antecipada _early-stop_ assim que ambas as tags respondem).
9. **Leituras por Medição:** **300 varreduras consecutivas** de DMRT por medição (configurável via `--readings`).

---

## 3. Planejamento das Medições (7 a 12 Medições)

As medições **1 a 7** compõem a grade mínima planejada (semelhante aos 7 pontos do Experimento 6), podendo-se estender até **12 medições** conforme a quantidade de pontos amostrados no laboratório:

| Medição |    Código    | Umidade RainPoint (%) | Ground Truth Gravimétrico (%) | Leituras | Arquivo CSV Individual                    | Gráfico Individual                     |
| :-----: | :----------: | :-------------------: | :---------------------------: | :------: | :---------------------------------------- | :------------------------------------- |
| **01**  | `medicao_01` |      _A aferir_       |      _A associar no fim_      |   300    | `medicao_01_umidade_XXpct_resultados.csv` | `medicao_01_umidade_XXpct_grafico.png` |
| **02**  | `medicao_02` |      _A aferir_       |      _A associar no fim_      |   300    | `medicao_02_umidade_XXpct_resultados.csv` | `medicao_02_umidade_XXpct_grafico.png` |
| **03**  | `medicao_03` |      _A aferir_       |      _A associar no fim_      |   300    | `medicao_03_umidade_XXpct_resultados.csv` | `medicao_03_umidade_XXpct_grafico.png` |
| **04**  | `medicao_04` |      _A aferir_       |      _A associar no fim_      |   300    | `medicao_04_umidade_XXpct_resultados.csv` | `medicao_04_umidade_XXpct_grafico.png` |
| **05**  | `medicao_05` |      _A aferir_       |      _A associar no fim_      |   300    | `medicao_05_umidade_XXpct_resultados.csv` | `medicao_05_umidade_XXpct_grafico.png` |
| **06**  | `medicao_06` |      _A aferir_       |      _A associar no fim_      |   300    | `medicao_06_umidade_XXpct_resultados.csv` | `medicao_06_umidade_XXpct_grafico.png` |
| **07**  | `medicao_07` |      _A aferir_       |      _A associar no fim_      |   300    | `medicao_07_umidade_XXpct_resultados.csv` | `medicao_07_umidade_XXpct_grafico.png` |
| **08**  | `medicao_08` |     _(Opcional)_      |      _A associar no fim_      |   300    | `medicao_08_umidade_XXpct_resultados.csv` | `medicao_08_umidade_XXpct_grafico.png` |
| **09**  | `medicao_09` |     _(Opcional)_      |      _A associar no fim_      |   300    | `medicao_09_umidade_XXpct_resultados.csv` | `medicao_09_umidade_XXpct_grafico.png` |
| **10**  | `medicao_10` |     _(Opcional)_      |      _A associar no fim_      |   300    | `medicao_10_umidade_XXpct_resultados.csv` | `medicao_10_umidade_XXpct_grafico.png` |
| **11**  | `medicao_11` |     _(Opcional)_      |      _A associar no fim_      |   300    | `medicao_11_umidade_XXpct_resultados.csv` | `medicao_11_umidade_XXpct_grafico.png` |
| **12**  | `medicao_12` |     _(Opcional)_      |      _A associar no fim_      |   300    | `medicao_12_umidade_XXpct_resultados.csv` | `medicao_12_umidade_XXpct_grafico.png` |

---

## 4. Passo a Passo da Metodologia

### Etapa 1 — Coleta das Leituras de DMRT e Sensor RainPoint (Medições 1 a 7–12)

1. Posicione o vaso sob a antena a **55 cm de altura**.
2. Meça a umidade do solo com o sensor comercial **RainPoint** e anote o valor percentual.
3. Execute o `main.py` informando o número da medição (`--medicao 1..12`) e o valor lido no RainPoint (`--umidade`):
   ```bash
   python main.py --medicao 1 --umidade 22
   python main.py --medicao 2 --umidade 30
   python main.py --medicao 3 --umidade 42
   python main.py --medicao 4 --umidade 51
   python main.py --medicao 5 --umidade 60
   python main.py --medicao 6 --umidade 72
   python main.py --medicao 7 --umidade 85
   ```
   _(Caso utilize vasos diferentes em cada ponto, pode identificá-los opcionalmente com `--vaso "Vaso 02"`)._
4. Retire a amostra correspondente do vaso para a análise gravimétrica laboratorial externa.

### Etapa 2 — Associação Posterior do Ground Truth Gravimétrico

Quando os valores de umidade do Ground Truth gravimétrico (calculados fora) estiverem prontos, basta associá-los às medições já registradas por qualquer uma das 3 formas abaixo:

- **Opção A — Associar todos os valores de uma só vez em lote (na ordem das medições 1, 2, ...):**
  ```bash
  python main.py --groundtruth-list 18.4 26.2 35.0 44.8 53.1 64.5 77.2
  ```
- **Opção B — Associar individualmente a cada medição:**
  ```bash
  python main.py --medicao 1 --groundtruth 18.4
  python main.py --medicao 2 --groundtruth 26.2
  ```
- **Opção C — Editar diretamente a coluna `umidade_groundtruth_pct` em `experimento_9/consolidado_exp9.csv` e regenerar os gráficos:**
  ```bash
  python main.py --plot
  ```

---

## 5. Instruções de Uso do Código (`main.py`)

### 5.1 Verificar o Status Consolidado das Medições

```bash
python main.py --status
```

### 5.2 Executar uma Medição de DMRT + RainPoint

```bash
python main.py --medicao <1..12> --umidade <PERCENTUAL_RAINPOINT> [--vaso "Vaso 01"] [--readings 300]
```

### 5.3 Associar o Ground Truth Gravimétrico (Posteriormente)

```bash
# Individualmente por medição (não requer leitor RFID conectado):
python main.py --medicao <1..12> --groundtruth <PERCENTUAL_GRAVIMETRICO>

# Em lote para as medições 1, 2, ..., N:
python main.py --groundtruth-list <GT_1> <GT_2> <GT_3> ...
```

### 5.4 Atualizar Gráficos e Tabela Comparativa

```bash
python main.py --plot
```

---

## 6. Arquivos e Gráficos Gerados Automaticamente

- `experimento_9/consolidado_exp9.csv`: Tabela consolidada reunindo, para cada medição (1 a 12), a umidade do **RainPoint (%)**, a umidade **Ground Truth (%)**, a diferença `erro_rainpoint_vs_gt_pct`, as taxas de detecção, o **MRT** (bruto e filtrado EMA) e **RSSI** das tags de sensoriamento e referência, e o **DMRT** médio, desvio padrão, mínimo e máximo.
- `experimento_9/curva_dmrt_vs_umidade.png`: Painel duplo apresentando a curva de resposta do **DMRT vs Umidade** (RainPoint e Ground Truth gravimétrico) e o comportamento dos MRTs absolutos e taxa de detecção.
- `experimento_9/comparativo_groundtruth_rainpoint_dmrt.png`: Painel triplo gerado após a associação do Ground Truth, contendo:
  1. Curva de calibração **DMRT vs Ground Truth Gravimétrico (%)** com regressão linear ($R^2$ e $\text{RMSE}$);
  2. Comparação direta **Sensor Comercial RainPoint (%) vs Ground Truth (%)** frente à linha ideal 1:1;
  3. Gráfico de barras por medição comparando **Ground Truth (%)**, **RainPoint (%)** e **Umidade Estimada via DMRT (%)**.
- `experimento_9/medicao_0X_umidade_YYpct_resultados.csv` e `experimento_9/medicao_0X_umidade_YYpct_grafico.png`: Série temporal completa (300 leituras) de MRT, DMRT e RSSI de cada medição.

---

## 7. Registro de Resultados Consolidados

_(Tabela a ser preenchida com os dados consolidados em `experimento_9/consolidado_exp9.csv` após a coleta e associação do Ground Truth)_:

| Medição | Vaso | Umidade RainPoint (%) | Ground Truth Gravimétrico (%) | Erro RainPoint − GT (p.p.) | Leituras Válidas DMRT | Taxa Detecção (%) | MRT Sens Filtrado (dBm) | MRT Ref Filtrado (dBm) | DMRT Médio (dB) | Desvio Padrão DMRT (dB) | RSSI Sens Médio (dBm) | Data/Hora |
| :-----: | :--: | :-------------------: | :---------------------------: | :------------------------: | :-------------------: | :---------------: | :---------------------: | :--------------------: | :-------------: | :---------------------: | :-------------------: | :-------: |
| **01**  |      |                       |                               |                            |                       |                   |                         |                        |                 |                         |                       |           |
| **02**  |      |                       |                               |                            |                       |                   |                         |                        |                 |                         |                       |           |
| **03**  |      |                       |                               |                            |                       |                   |                         |                        |                 |                         |                       |           |
| **04**  |      |                       |                               |                            |                       |                   |                         |                        |                 |                         |                       |           |
| **05**  |      |                       |                               |                            |                       |                   |                         |                        |                 |                         |                       |           |
| **06**  |      |                       |                               |                            |                       |                   |                         |                        |                 |                         |                       |           |
| **07**  |      |                       |                               |                            |                       |                   |                         |                        |                 |                         |                       |           |

---

## 8. Gráficos Consolidados

![Curva de Umidade vs DMRT e MRT](curva_dmrt_vs_umidade.png)

![Comparativo Ground Truth Gravimétrico vs RainPoint e DMRT](comparativo_groundtruth_rainpoint_dmrt.png)

# Testes laboratorio

Amostra 1: DMRT 5.98 solo no vaso - 28 umidade - 76,63 solo + pote - Solo mineral - horizonte A
DMRT 7,68 solo no vaso - 39 umidade - 69,81 solo + pote - Solo turfa
