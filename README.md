# PDQ-Flow v1.0
## Pipeline de Dados sobre Queimadas

Pipeline que transfere automaticamente os dados abertos de focos de incêndio
do INPE para um banco PostgreSQL + PostGIS e os disponibiliza via serviços HTTP.

---

## Estrutura do projeto

```
pdqflow-v1/
├── docker-compose.yml          # Orquestração completa da stack
├── .env                        # Variáveis de ambiente (banco)
│
├── banco/
│   └── sql/
│       └── init.sql            # Schema, tabelas, índices e views PostGIS
│
├── etl/
│   ├── carga.py                # ETL: download INPE → limpeza → inserção PostGIS
│   ├── requirements.txt
│   └── Dockerfile
│
└── servicos/
    ├── config.py               # Configuração compartilhada (DB, versão)
    ├── requirements.txt
    ├── Dockerfile
    ├── focos/
    │   └── servico.py          # Rotas: focos individuais
    ├── espacial/
    │   └── servico.py          # Rotas: consultas espaciais PostGIS
    └── estatisticas/
        └── servico.py          # Rotas: agregações analíticas
```

---

## Como executar

### Pré-requisitos
- Docker e Docker Compose instalados

### 1. Subir a stack completa

```bash
docker compose up -d
```

O container `etl` executa a carga imediatamente ao subir e, depois,
repete automaticamente todo dia às 07:00 (horário de Brasília), usando o CSV
diário do dia anterior publicado pelo INPE.

### 2. Acompanhar a carga inicial

```bash
docker compose logs -f etl
```

### 3. Acessar os serviços

| Serviço          | URL                          | Descrição                        |
|------------------|------------------------------|----------------------------------|
| pgAdmin          | http://localhost:5050        | Interface visual do banco        |
| Focos            | http://localhost:7001        | Focos individuais                |
| Espacial         | http://localhost:7002        | Consultas espaciais (PostGIS)    |
| Estatísticas     | http://localhost:7003        | Agregações e séries temporais    |

**pgAdmin:** login `admin@pdqflow.com` / `admin123`
Adicionar servidor: host `banco`, porta `5432`, user `pdqflow`, senha `pdqflow123`

### 4. Parar tudo

```bash
docker compose down
```

Para apagar os dados do banco também:

```bash
docker compose down -v
```

---

## Rotas disponíveis

### Serviço Focos — porta 7001

| Método | Rota                          | Descrição                              |
|--------|-------------------------------|----------------------------------------|
| GET    | `/`                           | Informações do serviço                 |
| GET    | `/focos`                      | Lista focos (paginado: `?limite=&pagina=`) |
| GET    | `/focos/<id_inpe>`            | Foco específico pelo ID do INPE        |
| GET    | `/focos/estado/<estado>`      | Focos de um estado (ex: `BA`, `MT`)    |
| GET    | `/focos/bioma/<bioma>`        | Focos de um bioma (ex: `AMAZONIA`)     |
| GET    | `/focos/alto-risco`           | Focos com risco_fogo ≥ 0.8             |

### Serviço Espacial — porta 7002

| Método | Rota                              | Descrição                                              |
|--------|-----------------------------------|--------------------------------------------------------|
| GET    | `/`                               | Informações do serviço                                 |
| GET    | `/espacial/raio`                  | Focos em raio a partir de ponto (`?lat=&lon=&raio=km`) |
| GET    | `/espacial/geojson`               | Exporta focos como GeoJSON (`?estado=&bioma=`)         |
| GET    | `/espacial/clusters`              | Agrupamento DBSCAN (`?eps=&min_pts=`)                  |
| GET    | `/espacial/convex-hull/<estado>`  | Envoltória convexa dos focos de um estado              |
| GET    | `/espacial/densidade`             | Densidade de focos por grade de 1° × 1°                |

### Serviço Estatísticas — porta 7003

| Método | Rota                          | Descrição                                    |
|--------|-------------------------------|----------------------------------------------|
| GET    | `/`                           | Informações do serviço                       |
| GET    | `/estatisticas/total`         | Total de focos, datas e cobertura            |
| GET    | `/estatisticas/por-bioma`     | Totais e centróides geográficos por bioma    |
| GET    | `/estatisticas/por-estado`    | Totais, alto-risco e envelope por estado     |
| GET    | `/estatisticas/serie-temporal`| Série diária (`?dias=30`)                    |
| GET    | `/estatisticas/por-satelite`  | Distribuição por satélite detector           |
| GET    | `/estatisticas/log-carga`     | Histórico de execuções do ETL                |

---

## Recursos PostGIS utilizados

| Função PostGIS          | Onde é usada                                      |
|-------------------------|---------------------------------------------------|
| `ST_MakePoint`          | Construção da geometria no ETL                    |
| `ST_SetSRID`            | Define sistema de referência WGS84 (EPSG:4326)    |
| `ST_X / ST_Y`           | Extrai longitude/latitude de pontos               |
| `ST_AsGeoJSON`          | Serializa geometrias para GeoJSON                 |
| `ST_DWithin`            | Focos dentro de raio (via geografia)              |
| `ST_Distance`           | Distância real entre pontos em metros             |
| `ST_Collect`            | Agrega geometrias para operações em conjunto      |
| `ST_Centroid`           | Centróide geográfico de um conjunto de pontos     |
| `ST_ConvexHull`         | Envoltória convexa (forma aproximada de região)   |
| `ST_Envelope`           | Bounding box de um conjunto de geometrias         |
| `ST_ClusterDBSCAN`      | Agrupamento espacial por densidade                |
| `ST_SnapToGrid`         | Grade regular para análise de densidade           |
| `ST_Area`               | Área de polígono em m² (via cast para geography)  |
| Índice GiST             | Acelera todas as consultas espaciais              |

---

## Fonte dos dados

**INPE — Instituto Nacional de Pesquisas Espaciais**
Focos de incêndio: https://queimadas.dgi.inpe.br/queimadas/portal-static/situacao-atual/
CSV diário: `https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/`

O ETL trata o valor `-999` enviado pelo INPE como dado ausente nos campos numéricos.

Os dados são abertos e de domínio público (Lei n.º 12.527/2011).

---

## Próximas versões

- **v2.0**: Servidor MCP + interface de chat com LLM
- **v2.1**: Dashboard web com mapas interativos
