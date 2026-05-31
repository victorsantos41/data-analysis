# Implementation Notes

Este documento resume a evolucao da pipeline de dados do projeto Solarway, explicando:

- o papel de cada etapa
- o que entra e o que sai em cada camada
- por que cada transformacao foi criada
- o que pode ser extraido de negocio ao final do fluxo

## 1. Objetivo do Projeto

O objetivo da pipeline e identificar territorios com potencial comercial para energia solar.

A ideia central nao e apenas saber onde existe boa irradiacao solar, mas sim encontrar regioes que combinem:

- bom potencial solar
- contexto territorial consistente
- capacidade socioeconomica
- maior chance de conversao comercial

Em termos praticos, o objetivo final e responder:

- quais bairros ou regioes devem ser priorizados para prospeccao?
- onde faz sentido investir marketing?
- quais territorios combinam irradiacao com maior potencial de compra?

## 2. Visao Geral do Fluxo

Pipeline principal:

1. `raw_to_trusted.py`
2. `trusted_to_refined.py`
3. `refined_to_business.py`
4. `business_to_ibge.py`
5. `ibge_to_socioeconomic.py`
6. `socioeconomic_to_scoring.py`

Resumo do fluxo:

- `raw`: dado bruto original
- `trusted`: dado limpo e padronizado
- `refined`: dado enriquecido geograficamente
- `business`: dado agregado por territorio comercial
- `ibge`: dado com chave oficial de integracao publica
- `socioeconomic`: dado com contexto economico e urbano
- `scoring`: dado priorizado para decisao comercial

## 3. Controle de Processamento

### Arquivo `.processed`

Cada etapa da pipeline usa um arquivo `.processed` para controlar quais arquivos ja foram processados.

Como funciona:

- a etapa le os arquivos de entrada
- consulta o `.processed`
- ignora arquivos ja processados
- registra no `.processed` os arquivos processados com sucesso

Objetivo:

- evitar reprocessamento desnecessario
- impedir geracao duplicada de saidas
- permitir execucao incremental da pipeline

Uso em `dev`:

- para testar novamente, pode ser necessario limpar ou editar manualmente o `.processed`

## 4. Etapas do Pipeline

## 4.1 `raw_to_trusted.py`

### Papel
Transforma a base bruta em uma camada confiavel.

### Entrada
- arquivos CSV em `data/raw`

### O que faz
- le o CSV bruto
- remove duplicidades por `ID`
- trata valores nulos em campos numericos
- padroniza nomes de colunas
- converte o formato para JSON

### Saida
- arquivos JSON em `data/trusted`

### Objetivo
- preparar os dados para consumo nas proximas etapas

## 4.2 `trusted_to_refined.py`

### Papel
Enriquece os registros com contexto geografico.

### Entrada
- arquivos JSON da camada `trusted`

### O que faz
- realiza geocodificacao reversa via OpenStreetMap/Nominatim
- identifica cidade, bairro, CEP e endereco
- calcula medias sazonais da irradiacao

### Saida
- arquivos JSON em `data/refined`

### Objetivo
- transformar coordenadas em informacao territorial utilizavel

## 4.3 `refined_to_business.py`

### Papel
Transforma o dado tecnico em uma visao comercial agregada.

### Entrada
- arquivos JSON da camada `refined`

### O que faz
- agrupa registros por:
  - `state`
  - `city`
  - `suburb`
  - `postcode`
- calcula medias de irradiacao anual, mensal e sazonal
- conta quantos pontos compoem cada agrupamento

### Saida
- arquivos JSON em `data/business`

### Objetivo
- sair do nivel de ponto individual
- passar para o nivel de territorio comercial

### O que representa
Cada registro da camada `business` representa um territorio agregado.

Exemplo:

- um bairro/cidade/CEP com media de irradiacao e volume de pontos associados

## 4.4 `business_to_ibge.py`

### Papel
Adicionar uma chave oficial de integracao publica.

### Entrada
- arquivos JSON da camada `business`

### O que faz
- usa `city` e `state`
- consulta a API de localidades do IBGE
- identifica o municipio oficial
- adiciona o codigo IBGE do municipio

### Saida
- arquivos JSON em `data/ibge`

### Objetivo
- permitir integracao segura com bases oficiais externas

### Por que o dado fica melhor
Antes da camada `ibge`, os registros dependem principalmente de texto, como:

- nome da cidade
- nome do estado

Isso e bom para leitura humana, mas fragil para integracao.

Depois da camada `ibge`, o registro passa a ter:

- `ibge_city_code`

Esse codigo funciona como chave oficial para cruzamento com dados publicos.

### Campos adicionados

`ibge_city_code`
- codigo oficial do municipio no IBGE

`ibge_city_name`
- nome oficial do municipio encontrado na base do IBGE

`ibge_state_name`
- nome do estado associado ao municipio

`ibge_state_acronym`
- sigla da unidade federativa

`ibge_match_status`
- status do cruzamento com o IBGE

## 4.5 `ibge_to_socioeconomic.py`

### Papel
Enriquecer cada registro com proxies socioeconomicos municipais.

### Entrada
- arquivos JSON da camada `ibge`

### O que faz
- usa `ibge_city_code` como chave
- consulta tabelas do IBGE/SIDRA
- adiciona proxies de renda, perfil domiciliar, urbanizacao e infraestrutura

### Saida
- arquivos JSON em `data/socioeconomic`

### Objetivo
- adicionar contexto economico e urbano ao potencial solar

### Proxies atualmente utilizados

`income_avg`
- proxy de renda
- calculada a partir de PIB municipal e populacao residente

`household_indicator_value`
- proxy de perfil domiciliar
- baseada em conexao domiciliar a internet

`urban_indicator_value`
- proxy de urbanizacao
- baseada na proporcao de domicilios urbanos

`sanitation_indicator_value`
- proxy de infraestrutura
- baseada na proporcao de domicilios com esgotamento por rede geral

### Campos de apoio tambem adicionados

- `gdp_total`
- `population_total`
- `households_total_for_internet`
- `households_with_internet`
- `households_total_for_urban`
- `urban_households`
- `households_total_for_sanitation`
- `households_with_sewage_network`

### Observacao importante
A vulnerabilidade social ainda esta pendente de integracao complementar, por exemplo com Ipea/Atlas.

## 4.6 `socioeconomic_to_scoring.py`

### Papel
Gerar a ultima camada principal do pipeline analitico: o score comercial.

### Entrada
- arquivos JSON da camada `socioeconomic`

### O que faz
- normaliza os indicadores do lote
- transforma cada indicador em score
- compoe um score final ponderado
- classifica prioridade comercial
- gera ranking dos territorios

### Saida
- arquivos JSON em `data/scoring`

### Objetivo
- transformar dado tecnico e socioeconomico em priorizacao comercial

### Pesos implementados atualmente

- `45%` irradiacao solar
- `25%` proxy economica
- `15%` perfil domiciliar
- `10%` urbanizacao
- `5%` saneamento

### Campos gerados

`solar_score`
- score do potencial solar

`income_score`
- score da proxy economica

`household_score`
- score do perfil domiciliar

`urban_score`
- score de urbanizacao

`sanitation_score`
- score de infraestrutura basica

`solar_lead_score`
- score final consolidado do territorio

`lead_priority`
- classificacao textual da prioridade

`lead_rank`
- posicao do territorio no ranking do lote

## 5. Diferenca Entre as Camadas Analiticas

### `refined`
- foco tecnico e geografico
- registro ainda e um ponto individual

### `business`
- foco comercial e territorial
- registro vira um agrupamento por bairro/cidade/CEP

### `ibge`
- foco de integracao oficial
- registro ganha codigo oficial do municipio

### `socioeconomic`
- foco em contexto economico e urbano
- registro ganha proxies municipais de apoio ao score

### `scoring`
- foco em decisao comercial
- registro ganha score, prioridade e ranking

## 6. O Que Podemos Tirar Dos Dados Coletados

Ao final do pipeline, principalmente na camada `scoring`, ja e possivel extrair metricas praticas de negocio.

## 6.1 Ranking de territorios

Com `lead_rank` e `solar_lead_score`, voce consegue identificar:

- top bairros/regioes para prospeccao
- territorios com melhor potencial comercial
- lista de prioridade para o time comercial

## 6.2 Segmentacao por prioridade

Com `lead_priority`, e possivel separar territorios em faixas como:

- alta
- media alta
- media
- media baixa
- baixa

Isso ajuda a decidir:

- onde investir primeiro
- onde fazer abordagem mais agressiva
- onde apenas monitorar

## 6.3 Forca tecnica do potencial solar

Com `solar_score`, e possivel entender:

- quais territorios sao tecnicamente mais favoraveis
- onde a irradiacao e realmente um diferencial forte

## 6.4 Forca economica do municipio

Com `income_score`, e possivel identificar:

- municipios com melhor proxy de capacidade economica
- territorios que podem sustentar ticket medio mais alto

## 6.5 Perfil domiciliar e maturidade de consumo

Com `household_score`, e possivel observar:

- regioes com maior nivel de conexao domiciliar
- territorios com sinal de maior maturidade estrutural

## 6.6 Grau de urbanizacao

Com `urban_score`, e possivel ver:

- areas mais urbanizadas
- municipios ou territorios com estrutura urbana mais consolidada

## 6.7 Infraestrutura basica

Com `sanitation_score`, e possivel medir:

- infraestrutura minima urbana
- qualidade territorial como proxy de organizacao urbana

## 6.8 Analise combinada

Com o `solar_lead_score`, voce consegue combinar:

- potencial solar
- potencial economico
- perfil domiciliar
- urbanizacao
- infraestrutura

Ou seja, o score final serve para responder:

- onde vender primeiro
- onde vale investir marketing
- quais bairros ou regioes tem maior chance de conversao

## 7. Como Isso Ajuda Na Pratica

Com o pipeline completo, o projeto deixa de ser apenas uma base tecnica de irradiacao e passa a ser uma ferramenta de apoio comercial.

Aplicacoes praticas:

- montar ranking de bairros prioritarios
- orientar campanhas de trafego pago
- apoiar planejamento comercial regional
- filtrar territorios com maior chance de compra
- identificar regioes boas tecnicamente, mas fracas economicamente
- identificar regioes boas economicamente, mas com menor vantagem solar

## 8. Resumo Final

O fluxo construido ate aqui transforma:

- coordenadas e irradiacao solar

em:

- territorios agregados
- municipios oficiais
- contexto socioeconomico
- score final de priorizacao comercial

Em termos de negocio, a pipeline agora permite:

- priorizar bairros e regioes
- embasar prospeccao com dados
- reduzir decisao puramente intuitiva
- preparar o terreno para evolucoes futuras, como:
  - vulnerabilidade social real
  - IPTU
  - valor imobiliario
  - dashboards
  - integracao com CRM
