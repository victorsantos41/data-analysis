## 2026-05-06 17:30:00 - Refactor do fluxo trusted -> refined

Implementei a fusao operacional entre refined e business dentro de `trusted_to_refined.py`, com agregacao direta da camada refined, cache persistente de geocoding em disco, manifest/sidecar de metadados, e rejeitados separados da saida principal. Tambem adaptei `business_to_ibge.py` para consumir o novo refined agregado, desativei `refined_to_business.py`, extraí utilitarios compartilhados para `etl_utils.py` e adicionei `location_cache.py` para lookup local por coordenada e reaproveitamento de dados ja processados.

## 2026-05-06 20:35:00 - Correcao do filtro de arquivos trusted

Corrigi `trusted_to_refined.py` para ignorar arquivos `solar_data_trusted_meta_*.json` e `*_manifest_*.json`, evitando que sidecars de metadados sejam tratados como lotes de registros. Tambem adicionei umsa validacao defensiva para exigir que a entrada trusted seja um JSON array antes do processamento.

## 2026-05-06 20:45:00 - Simplificacao da camada refined para Lambda

Reduzi a saida da camada `refined` para apenas dois arquivos por execucao: o JSON principal agregado e o JSON de rejeitados. Removi a geracao de `meta` e `manifest` dessa camada, mantive as estatisticas apenas em log, e adaptei `business_to_ibge.py` para reconhecer o `refined` principal pelo schema do payload, sem depender mais de sidecars.

## 2026-05-10 20:30:00 - Restauracao do raw_to_trusted local

Restaurei `raw_to_trusted.py` para o comportamento local anterior a tentativa de adaptacao para Lambda. A etapa voltou a ler de `data/raw`, gravar em `data/trusted` e deixar de gerar o arquivo `solar_data_trusted_meta_*.json`.

## 2026-05-12 10:15:00 - Municipality resolver autocontido para Lambda

Refatorei `municipality_resolver.py` para ficar autocontido e pronto para empacotamento em um `.zip` de Lambda junto com `trusted_to_refined.py`. Removi as dependencias de `etl_utils.py` e `location_cache.py`, incorporei `haversine_km`, troquei a leitura de JSON por `json.load()` nativo, desativei a persistencia de cache em disco e mantive apenas cache em memoria durante a execucao.

## 2026-05-16 20:45:00 - Timeout do trusted_to_refined reduzido via assets locais

Adaptei `trusted_to_refined.py` para remover a dependencia do `support bucket` no runtime da Lambda. Os arquivos `ibge_sp_municipios_geo_fixed.geojson` e `ibge_municipios_sp_test.json` agora devem ser empacotados no deploy, e o `MunicipalityResolver` passou a ser inicializado em escopo global para reaproveitamento em invocacoes quentes. Tambem removi o download dos assets dentro do `lambda_handler` e simplifiquei a configuracao para usar apenas buckets de entrada e saida.
