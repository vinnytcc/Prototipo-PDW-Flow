"""
PDQ-Flow v1.0 — Serviço: Estatísticas
======================================
Agregações analíticas: totais por bioma, estado, série temporal.
Consultas aproveitam índices e views do PostGIS.
"""

from flask import Flask, jsonify, make_response, request
import psycopg
from psycopg.rows import dict_row
from flask_cors import CORS
from config import DB_CONFIG, DESCRICAO_APP, VERSAO

servico = Flask("estatisticas")
CORS(servico)


def get_conn():
    return psycopg.connect(**DB_CONFIG, row_factory=dict_row)


def resposta(dados, status=200):
    return make_response(jsonify(dados), status)


# ─── Rotas ────────────────────────────────────────────────────

@servico.get("/")
def info():
    return resposta({"descricao": "Serviço de estatísticas — " + DESCRICAO_APP, "versao": VERSAO})


@servico.get("/estatisticas/total")
def total_focos():
    """Retorna o total de focos e datas mínima/máxima do banco."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*)             AS total_focos,
                MIN(data_hora_gmt)   AS data_inicio,
                MAX(data_hora_gmt)   AS data_fim,
                COUNT(DISTINCT estado) AS estados_afetados,
                COUNT(DISTINCT bioma)  AS biomas_afetados
            FROM pdqflow.focos
            """
        )
        return resposta(cur.fetchone())


@servico.get("/estatisticas/por-bioma")
def por_bioma():
    """
    Totais por bioma com risco médio e FRP médio.
    Inclui centróide geográfico dos focos por bioma (PostGIS ST_Centroid).
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                bioma,
                total_focos,
                risco_medio,
                frp_medio_mw,
                frp_maximo_mw,
                media_dias_sem_chuva,
                centroide_geojson
            FROM pdqflow.vw_focos_por_bioma
            """
        )
        return resposta(cur.fetchall())


@servico.get("/estatisticas/por-estado")
def por_estado():
    """
    Totais por estado com focos de alto risco e envelope geográfico.
    Usa ST_Envelope para calcular bounding box do estado via focos.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                estado,
                total_focos,
                risco_medio,
                frp_medio_mw,
                focos_alto_risco,
                envelope_geojson
            FROM pdqflow.vw_focos_por_estado
            """
        )
        return resposta(cur.fetchall())


@servico.get("/estatisticas/serie-temporal")
def serie_temporal():
    """
    Série histórica diária de focos.
    Query params: dias (padrão 30)
    """
    dias = int(request.args.get("dias", 30))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT data, total_focos, estados_afetados, risco_medio, frp_total_mw
            FROM pdqflow.vw_serie_temporal
            LIMIT %s
            """,
            (dias,),
        )
        return resposta(cur.fetchall())


@servico.get("/estatisticas/por-satelite")
def por_satelite():
    """Distribuição de focos por satélite detector."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                satelite,
                COUNT(*)                           AS total_focos,
                ROUND(AVG(risco_fogo)::NUMERIC, 3) AS risco_medio,
                ROUND(AVG(frp)::NUMERIC, 1)        AS frp_medio_mw
            FROM pdqflow.focos
            GROUP BY satelite
            ORDER BY total_focos DESC
            """
        )
        return resposta(cur.fetchall())


@servico.get("/estatisticas/log-carga")
def log_carga():
    """Histórico de execuções do ETL."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT arquivo, total_linhas, inseridos, duplicados,
                   erros, iniciado_em, finalizado_em, status
            FROM pdqflow.log_carga
            ORDER BY iniciado_em DESC
            LIMIT 20
            """
        )
        return resposta(cur.fetchall())


if __name__ == "__main__":
    servico.run(host="0.0.0.0", port=5000, debug=True)
