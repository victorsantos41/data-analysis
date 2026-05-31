# Solar Irradiation Pipeline (Clean Architecture)

Este projeto implementa uma pipeline de processamento de dados de irradiação solar no estado de São Paulo, seguindo os princípios de **Clean Architecture** e o padrão **Strategy**.

## Estrutura do Projeto (Simplified)

Para evitar débito técnico e complexidade desnecessária, a pipeline foi simplificada em dois scripts principais:

1.  **raw_to_trusted.py**: Faz a limpeza inicial dos dados CSV, deduplicação, padronização de nomes para inglês e arredondamento para 1 casa decimal. Salva o resultado em JSON na camada TRUSTED.
2.  **trusted_to_refined.py**: Realiza o enriquecimento geográfico (OpenStreetMap), calcula médias sazonais (summer, autumn, winter, spring) e garante que apenas registros com CEP e Bairro válidos sejam salvos na camada REFINED.

> [!NOTE]
> A implementação anterior em **Clean Architecture** foi movida para o diretório `architecture/clean-arch/` para referência futura.

## Como Executar

### Pré-requisitos

- Python 3.10+
- Bibliotecas: `pandas`, `python-dotenv`

### Instalação

1.  **Ativar o ambiente virtual:**
    - **Windows (PowerShell):** `.\venv\Scripts\Activate.ps1`

2.  **Instalar dependências:**
    ```bash
    pip install pandas python-dotenv
    ```

### Execução dos Jobs

A execução agora é feita através de scripts individuais:

```bash
# 1. Processar dados brutos para a camada Trusted
python raw_to_trusted.py

# 2. Refinar dados da camada Trusted para a camada Refined
python trusted_to_refined.py
```

## Estratégia Dev vs Prod

A escolha da arquitetura permite que o `LocalStorageProvider` seja substituído por um `S3StorageProvider` (AWS Glue/S3) apenas alterando a variável de ambiente `PIPELINE_PROFILE`, sem tocar na lógica de negócio.
