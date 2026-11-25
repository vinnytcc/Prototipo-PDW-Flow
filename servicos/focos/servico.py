"""
PDQ-Flow v1.0 — Serviço: Focos de Queimadas
============================================
Rotas de acesso aos registros individuais de focos.
Banco: PostgreSQL + PostGIS via psycopg3
"""

from flask import Flask, jsonify, make_response, request
import psycopg
from psycopg.rows import dict_row
from flask_cors import CORS
from config import DB_CONFIG, DESCRICAO_APP, VERSAO

servico = Flask("focos")
CORS(servico)

# ─── Helpers ──────────────────────────────────────────────────
def get_conn():
    return psycopg.connect(**DB_CONFIG, row_factory=dict_row)


def resposta(dados, status=200):
    return make_response(jsonify(dados), status)


# ─── Rotas ────────────────────────────────────────────────────

@servico.get("/")
def info():
    """Informações gerais do serviço."""
    return resposta({"descricao": "Serviço de focos — " + DESCRICAO_APP, "versao": VERSAO})


@servico.get("/focos")
def listar_focos():
    """
    Lista focos com paginação.
    Query params: limite (padrão 100, max 1000), pagina (padrão 1)
    """
    limite = min(int(request.args.get("limite", 100)), 1000)
    pagina = max(int(request.args.get("pagina", 1)), 1)
    offset = (pagina - 1) * limite

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id_inpe, data_hora_gmt, satelite, municipio,
                estado, bioma, risco_fogo, frp,
                numero_dias_sem_chuva, precipitacao,
                ST_X(geom) AS longitude,
                ST_Y(geom) AS latitude
            FROM pdqflow.focos
            ORDER BY data_hora_gmt DESC
            LIMIT %s OFFSET %s
            """,
            (limite, offset),
        )
        focos = cur.fetchall()

        cur.execute("SELECT COUNT(*) AS total FROM pdqflow.focos")
        total = cur.fetchone()["total"]

    return resposta({
        "pagina": pagina,
        "limite": limite,
        "total_registros": total,
        "focos": focos,
    })


@servico.get("/focos/estado/<string:estado>")
def focos_por_estado(estado: str):
    """Retorna focos de um estado específico (case-insensitive)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id_inpe, data_hora_gmt, municipio, estado,
                bioma, risco_fogo, frp,
                ST_X(geom) AS longitude,
                ST_Y(geom) AS latitude
            FROM pdqflow.focos
            WHERE UPPER(estado) = UPPER(%s)
            ORDER BY data_hora_gmt DESC
            LIMIT 500
            """,
            (estado,),
        )
        focos = cur.fetchall()

    return resposta({"estado": estado.upper(), "total": len(focos), "focos": focos})


@servico.get("/focos/bioma/<string:bioma>")
def focos_por_bioma(bioma: str):
    """Retorna focos de um bioma específico."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id_inpe, data_hora_gmt, municipio, estado,
                bioma, risco_fogo, frp,
                ST_X(geom) AS longitude,
                ST_Y(geom) AS latitude
            FROM pdqflow.focos
            WHERE UPPER(bioma) = UPPER(%s)
            ORDER BY risco_fogo DESC
            LIMIT 500
            """,
            (bioma,),
        )
        focos = cur.fetchall()

    return resposta({"bioma": bioma.upper(), "total": len(focos), "focos": focos})


@servico.get("/focos/alto-risco")
def focos_alto_risco():
    """
    Retorna focos com risco_fogo >= 0.8.
    Usa a view pdqflow.vw_focos_alto_risco.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id_inpe, data_hora_gmt, municipio, estado,
                bioma, risco_fogo, frp, numero_dias_sem_chuva,
                longitude, latitude
            FROM pdqflow.vw_focos_alto_risco
            LIMIT 500
            """
        )
        focos = cur.fetchall()

    return resposta({"total": len(focos), "focos": focos})


@servico.get("/focos/<string:id_inpe>")
def foco_por_id(id_inpe: str):
    """Retorna um foco específico pelo id do INPE."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                id_inpe, data_hora_gmt, satelite, municipio,
                estado, pais, municipio_id, estado_id,
                bioma, risco_fogo, frp,
                numero_dias_sem_chuva, precipitacao,
                ST_X(geom) AS longitude,
                ST_Y(geom) AS latitude,
                ST_AsGeoJSON(geom)::JSON AS geojson
            FROM pdqflow.focos
            WHERE id_inpe = %s
            """,
            (id_inpe,),
        )
        foco = cur.fetchone()

    if not foco:
        return resposta({"erro": "Foco não encontrado"}, 404)
    return resposta(foco)


if __name__ == "__main__":
    servico.run(host="0.0.0.0", port=5000, debug=True)
