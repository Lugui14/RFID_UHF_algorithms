# Registro do Experimento 1 - Medição DMRT em Copos com Tags RFID UHF

## 1. Visão Geral

Este documento registra a configuração, mapeamento de tags EPC e parâmetros do **Experimento 1** para medição do Limiar Mínimo de Resposta Diferencial (DMRT) utilizando o leitor **IN-R200 (MagicRF M100)** e a metodologia do artigo *GreenTag* (ACM TOSN 2025).

---

## 2. Mapeamento das Tags por Copo (Experimento 1)

Convenção: `DMRT = Filtered_MRT(Sensoriamento) - Filtered_MRT(Referência)`

### 2.1. Copo Direita
- **Tag de Sensoriamento (Inferior):** `E2806995000040136FD09975`
- **Tag de Referência (Superior):** `E2806995000050136FD09175`

### 2.2. Copo Esquerda
- **Tag de Sensoriamento (Inferior):** `E2806995000040136FD09575`
- **Tag de Referência (Superior):** `E2806995000040136FD08D75`

---

## 3. Formato do Arquivo de Anotações (`anotacoes.md`)

Para carregar este experimento no script principal (`main.py`), o arquivo `anotacoes.md` deve conter o seguinte conteúdo:

```text
sensoriamento - referencia

copo direita: E2806995000040136FD09975 - E2806995000050136FD09175

copo esquerda: E2806995000040136FD09575 - E2806995000040136FD08D75
```

---

## 4. Instruções para Reprodução

1. Conecte o leitor RFID UHF IN-R200 na porta USB (`/dev/ttyUSB0`).
2. Certifique-se de que o arquivo `anotacoes.md` contenha o mapeamento acima (ou substitua pelas tags de um novo experimento).
3. Execute o monitoramento em tempo real:
   ```bash
   python main.py
   ```
4. Ao finalizar a coleta (pressionando `Ctrl+C`), o gráfico `dmrt_results.png` e os dados brutos `dmrt_results.csv` serão gerados automaticamente.
