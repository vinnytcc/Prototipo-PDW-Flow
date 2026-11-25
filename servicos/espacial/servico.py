"""
PDQ-Flow v1.0 — Serviço: Consultas Espaciais (PostGIS)
=======================================================
Rotas que exploram as capacidades espaciais do PostGIS:
  - ST_DWithin  → focos próximos a um ponto (raio em km)
  - ST_Within   → focos dentro de um polígono (GeoJSON)
  - ST_Distance → distância entre dois focos
  - ST_ClusterDBSCAN → agrupamento espacial de focos
  - ST_Convex Hull → envoltória dos focos de um estado
  - GeoJSON     → exportação de focos no formato GeoJSON padrão
"""

from flask import Flask, jsonify, make_response, request
import psycopg
from psycopg.rows import dict_row
from flask_cors import CORS
import json
from config import DB_CONFIG, DESCRICAO_APP, VERSAO

servico = Flask("espacial")
CORS(servico)


def get_conn():
    return psycopg.connect(**DB_CONFIG, row_factory=dict_row)


def resposta(dados, status=200):
    return make_response(jsonify(dados), status)


# ─── Rotas ────────────────────────────────────────────────────

@servico.get("/")
def info():
    return resposta({"descricao": "Serviço espacial — " + DESCRICAO_APP, "versao": VERSAO})


@servico.get("/espacial/raio")
def focos_em_raio():
    """
    Focos dentro de um raio a partir de um ponto central.
    Query params:
      lat  (float)  — latitude do ponto central
      lon  (float)  — longitude do ponto central
      raio (float)  — raio em quilômetros (padrão 100 km)

    Usa ST_DWithin com cast para geography → cálculo em metros reais.
    """
    lat  = float(request.args.get("lat",  -15.7801))  # padrão: Brasília
    lon  = float(request.args.get("lon",  -47.9292))
    raio = float(request.args.get("raio", 100)) * 1000  # km → m

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id_inpe, data_hora_gmt, municipio, estado, bioma,
                risco_fogo, frp,
                ST_X(geom)                         AS longitude,
                ST_Y(geom)                         AS latitude,
                ROUND(
                    (ST_Distance(
                        geom::geography,
                        ST_MakePoint(%s, %s)::geography
                    ) / 1000)::NUMERIC, 2
                )                                  AS distancia_km
            FROM pdqflow.focos
            WHERE ST_DWithin(
                geom::geography,
                ST_MakePoint(%s, %s)::geography,
                %s
            )
            ORDER BY distancia_km ASC
            LIMIT 200
            """,
            (lon, lat, lon, lat, raio),
        )
        focos = cur.fetchall()

    return resposta({
        "ponto_central": {"latitude": lat, "longitude": lon},
        "raio_km": raio / 1000,
        "total": len(focos),
        "focos": focos,
    })


@servico.get("/espacial/geojson")
def exportar_geojson():
    """
    Exporta focos no formato GeoJSON FeatureCollection.
    Query params: estado, bioma (opcionais para filtrar)
    Usa ST_AsGeoJSON do PostGIS para serialização correta.
    """
    estado = request.args.get("estado")
    bioma  = request.args.get("bioma")

    filtros = []
    params  = []
    if estado:
        filtros.append("UPPER(estado) = UPPER(%s)")
        params.append(estado)
    if bioma:
        filtros.append("UPPER(bioma) = UPPER(%s)")
        params.append(bioma)

    clausula_where = ("WHERE " + " AND ".join(filtros)) if filtros else ""

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(geom)::json,
                        'properties', json_build_object(
                            'id_inpe',    id_inpe,
                            'data',       data_hora_gmt,
                            'municipio',  municipio,
                            'estado',     estado,
                            'bioma',      bioma,
                            'risco_fogo', risco_fogo,
                            'frp',        frp
                        )
                    )
                )
            ) AS geojson
            FROM pdqflow.focos
            {clausula_where}
            LIMIT 1000
            """,
            params,
        )
        resultado = cur.fetchone()

    return make_response(
        jsonify(resultado["geojson"] if resultado else {}), 200
    )


@servico.get("/espacial/clusters")
def clusters_espaciais():
    """
    Agrupa focos em clusters espaciais usando ST_ClusterDBSCAN do PostGIS.
    Query params:
      eps      (float) — raio do cluster em graus (padrão 0.5° ≈ 55 km)
      min_pts  (int)   — mínimo de pontos por cluster (padrão 5)
    """
    eps     = float(request.args.get("eps",     0.5))
    min_pts = int(request.args.get("min_pts",   5))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                cluster_id,
                COUNT(*)                            AS total_focos,
                ROUND(AVG(risco_fogo)::NUMERIC, 3)  AS risco_medio,
                ROUND(AVG(frp)::NUMERIC, 1)         AS frp_medio_mw,
                ST_AsGeoJSON(
                    ST_Centroid(ST_Collect(geom))
                )::JSON                             AS centroide_geojson,
                ST_AsGeoJSON(
                    ST_ConvexHull(ST_Collect(geom))
                )::JSON                             AS convex_hull_geojson
            FROM (
                SELECT
                    geom, risco_fogo, frp,
                    ST_ClusterDBSCAN(geom, %s, %s) OVER () AS cluster_id
                FROM pdqflow.focos
            ) sub
            WHERE cluster_id IS NOT NULL
            GROUP BY cluster_id
            ORDER BY total_focos DESC
            """,
            (eps, min_pts),
        )
        clusters = cur.fetchall()

    return resposta({
        "parametros": {"eps_graus": eps, "min_pontos": min_pts},
        "total_clusters": len(clusters),
        "clusters": clusters,
    })


@servico.get("/espacial/convex-hull/<string:estado>")
def convex_hull_estado(estado: str):
    """
    Retorna o convex hull (envoltória convexa) dos focos de um estado.
    Demonstra ST_ConvexHull + ST_Collect do PostGIS.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                estado,
                COUNT(*)                                       AS total_focos,
                ST_AsGeoJSON(ST_ConvexHull(ST_Collect(geom)))::JSON AS convex_hull,
                ST_Area(
                    ST_ConvexHull(ST_Collect(geom))::geography
                ) / 1e6                                        AS area_km2
            FROM pdqflow.focos
            WHERE UPPER(estado) = UPPER(%s)
            GROUP BY estado
            """,
            (estado,),
        )
        resultado = cur.fetchone()

    if not resultado:
        return resposta({"erro": f"Nenhum foco encontrado para estado: {estado}"}, 404)
    return resposta(resultado)


@servico.get("/espacial/densidade")
def densidade_por_grade():
    """
    Calcula densidade de focos agrupando por grade de 1° × 1°.
    Usa ST_SnapToGrid do PostGIS para criar a grade e COUNT para densidade.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ST_X(ST_SnapToGrid(geom, 1.0)) AS lon_grade,
                ST_Y(ST_SnapToGrid(geom, 1.0)) AS lat_grade,
                COUNT(*)                        AS focos_na_celula,
                ROUND(AVG(risco_fogo)::NUMERIC, 2) AS risco_medio
            FROM pdqflow.focos
            GROUP BY ST_SnapToGrid(geom, 1.0)
            ORDER BY focos_na_celula DESC
            LIMIT 100
            """
        )
        grade = cur.fetchall()

    return resposta({"total_celulas": len(grade), "grade": grade})


if __name__ == "__main__":
    servico.run(host="0.0.0.0", port=5000, debug=True)
