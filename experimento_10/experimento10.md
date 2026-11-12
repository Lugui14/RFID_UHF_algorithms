# Experimento 10 - Medições de DMRT (200 Leituras) + RSSI Fixo a 26 dBi (+200 Leituras) nas Tags 09-01 a 09-18

## 1. Visão Geral

O **Experimento 10** segue a estrutura do **Experimento 9**, utilizando os **18 pares de tags** mapeados em `anotacoes.md` (`09-01` a `09-18`) e adicionando uma segunda etapa de coleta em potência fixa para cada teste:

1. **Etapa 1 — 200 Leituras Padrões de DMRT:** Varredura linear de potência RF de `15.0 dBm` a `26.0 dBm` (passo de `1.0 dBm` com _early-stop_), registrando o MRT bruto e filtrado (EMA), o RSSI no limiar e o diferencial $\text{DMRT} = \text{MRT}_{\text{sens}} - \text{MRT}_{\text{ref}}$.
2. **Etapa 2 — +200 Leituras Apenas de RSSI a 26 dBi (26.0 dBm):** Logo após concluir as 200 leituras de DMRT, a potência de transmissão do leitor é fixada em **26 dBi (26.0 dBm)** e são executadas **+200 leituras exclusivas de RSSI** das tags de Sensoriamento e Referência.
3. **Execução sem Ordem Fixa e Alteração Livre de Tags:** Qualquer teste pode ser executado em qualquer ordem, repetido ou renomeado, e os EPCs das tags podem ser alterados a qualquer momento (em `anotacoes.md`, em `TAG_PAIRS_EXP10` no `main.py`, via `--tag`/`--ref` ou via `--set-tag`).
4. **Compilação Manual de Curva:** Os dados são consolidados em `experimento_10/consolidado_exp10.csv` sem geração automática de gráfico de curva final.

---

## 2. Catálogo dos 18 Pares de Tags (`09-01` a `09-18`)

| Código do Par | Tag de Sensoriamento (EPC) | Tag de Referência (EPC) |
| :-----------: | :------------------------: | :---------------------: |
|   `09-01`     | `E2806995000040136FD0C575` | `E2806995000040136FD0C975` |
|   `09-02`     | `E2806995000040136FD0D175` | `E2806995000050136FD0CD75` |
|   `09-03`     | `E2806995000050136FD0D975` | `E2806995000050136FD0D575` |
|   `09-04`     | `E2806995000040136FD0DD75` | `E2806995000040136FD0E175` |
|   `09-05`     | `E2806995000050136FD0E575` | `E2806995000050136FD0E975` |
|   `09-06`     | `E2806995000050136FD0F175` | `E2806995000040136FD0ED75` |
|   `09-07`     | `E2806995000040136FD0F975` | `E2806995000040136FD0F575` |
|   `09-08`     | `E2806995000050136FD0FD75` | `E2806995000040136FD10175` |
|   `09-09`     | `E2806995000050136FD10575` | `E2806995000050136FD10975` |
|   `09-10`     | `E2806995000040136FD10D75` | `E2806995000050136FD11175` |
|   `09-11`     | `E2806995000040136FD11575` | `E2806995000040136FD11975` |
|   `09-12`     | `E2806995000050136FD11D75` | `E2806995000050136FD12175` |
|   `09-13`     | `E2806995000040136FD12575` | `E2806995000040136FD12975` |
|   `09-14`     | `E2806995000050136FD12D75` | `E2806995000040136FD13175` |
|   `09-15`     | `E2806995000050136FD13575` | `E2806995000050136FD13975` |
|   `09-16`     | `E2806995000040136FD13D75` | `E2806995000050136FD14175` |
|   `09-17`     | `E2806995000040136FD14575` | `E2806995000040136FD14975` |
|   `09-18`     | `E2806995000050136FD14D75` | `E2806995000040136FD0BD75` |

---

## 3. Como Executar (em Qualquer Ordem)

```bash
# 1. Executar passando diretamente o código do par (09-01 a 09-18 ou 1 a 18):
python main.py 09-01
python main.py 09-18
python main.py 7

# 2. Executar com um nome personalizado e escolhendo o par (--par / -p):
python main.py xp-100-4 --par 09-04
python main.py --nome amostra_turfa --par 09-12

# 3. Executar com nome terminado no número do par (seleciona 09-XX automaticamente):
python main.py xp-fin-100-4
python main.py xp-fin-500-18

# 4. Executar de forma interativa (pergunta o par e o nome no terminal):
python main.py

# 5. Sobrescrever manualmente os EPCs de Sensoriamento e/ou Referência em uma execução:
python main.py 09-06 --tag E2806995000040136FD0E175 --ref E2806995000040136FD0ED75

# 6. Salvar alteração permanente do EPC de um par em anotacoes.md e tags_mapeadas.json:
python main.py --set-tag 09-06 E2806995000040136FD0E175 E2806995000040136FD0ED75

# 7. Listar os 18 pares de tags ou consultar o resumo consolidado:
python main.py --tags
python main.py --status
```
