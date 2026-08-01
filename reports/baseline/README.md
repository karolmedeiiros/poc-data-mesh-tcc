# Baseline de Reports

Esta pasta contém os relatórios de referência do estado **verde** da arquitetura.

## Propósito

Os arquivos aqui representam o cenário em que todos os validadores passam:
- contratos estão de acordo com as políticas arquiteturais;
- qualidade dos dados está 100%;
- governança computacional, compliance e QoS estão em PASS.

## Uso

Antes de realizar mudanças manuais nos contratos ou dados, estes relatórios podem
ser usados como referência. Depois das mudanças, rode os validadores novamente e
compare os `reports/` atuais contra os arquivos desta pasta para detectar
drift, divergências e quebras de governança.

## Como recriar

Execute os validadores desejados e, em seguida, salve a baseline:

```bash
python3 governance/validate_contracts.py
python3 governance/validate_governance.py
python3 platform/quality/validate_data_quality.py
python3 governance/validate_computational_governance.py
python3 platform/quality/validate_qos.py
python3 platform/testing/save_baseline.py
```
