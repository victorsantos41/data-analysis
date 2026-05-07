# Dicionário de Dados - Pipeline de Irradiação Solar

Este documento descreve os campos e transformações em cada camada da pipeline.

## 1. Camada RAW (Entrada)

**Fonte:** `docs/labren-data/tilted_latitude_means_SP.csv`
**Formato:** CSV (Delimitador `;`)

| Campo     | Descrição                     | Tipo    |
| :-------- | :---------------------------- | :------ |
| ID        | Identificador único do ponto  | Inteiro |
| UF        | Unidade da Federação (Estado) | Texto   |
| LON       | Longitude                     | Decimal |
| LAT       | Latitude                      | Decimal |
| ANNUAL    | Média anual de irradiação     | Inteiro |
| JAN...DEC | Médias mensais de irradiação  | Inteiro |

## 2. Camada TRUSTED (Limpeza)

**Formato:** JSON

**Transformações:**

- Conversão de CSV para JSON.
- Deduplicação baseada no campo `id`.
- Tratamento de valores nulo (preenchimento com 0.0 para campos numéricos).
- Padronização de tipos (float para coordenadas e valores de irradiação).
- **Arredondamento:** Todos os valores numéricos são arredondados para **1 casa decimal**.

## 3. Camada REFINED (Enriquecimento)

**Formato:** JSON

**Campos Oficiais:**
| Campo | Descrição | Origem |
| :--- | :--- | :--- |
| id | Identificador original | RAW |
| lat / lon | Coordenadas Geográficas | RAW |
| city | Cidade / Município / Vila | OpenStreet API |
| suburb | Bairro / Distrito / Vilarejo | OpenStreet API |
| road | Nome da via / Estrada | OpenStreet API |
| postcode | CEP (Obrigatório) | OpenStreet API |
| full_address| String completa do endereço | OpenStreet API |
| annual | Média anual de irradiação | RAW |
| {MONTH} | Médias mensais (JAN, FEB, etc.) | RAW |
| summer_avg | Média (Jan, Fev, Dez) | Cálculo |
| autumn_avg | Média (Mar, Abr, Mai) | Cálculo |
| winter_avg | Média (Jun, Jul, Ago) | Cálculo |
| spring_avg | Média (Set, Out, Nov) | Cálculo |

**Regras de Negócio:**

- Registros sem `postcode` são descartados.
- Registros sem `suburb` são descartados.
- Todas as médias calculadas são arredondadas para **1 casa decimal**.

**Regra de Ouro:** Registros sem `codigo_postal` são descartados desta camada.
