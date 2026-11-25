"""
PDQ-Flow v1.0 — ETL de Focos de Queimadas
==========================================
Transfere automaticamente os dados abertos do INPE (CSV diário)
para o banco PostgreSQL + PostGIS.

Fonte: https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/
Execução: automática via APScheduler (diária às 07:00 BRT) + manual via CLI
"""

import os
import io
import csv
import logging
import urllib.request
from datetime import date, datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
import pandas as pd
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

# ─── Configuração ──────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pdqflow.etl")

# Conexão com o banco
DB_CONFIG = dict(
    host=os.getenv("DB_HOST", "banco"),
    port=int(os.getenv("DB_PORT", 5432)),
    user=os.getenv("DB_USER", "pdqflow"),
    password=os.getenv("DB_PASSWORD", "pdqflow123"),
    dbname=os.getenv("DB_NAME", "queimadas"),
)

# URL base do INPE — arquivo do último dia completo
def url_inpe_diario(data: date | None = None) -> tuple[str, str]:
    """Retorna a URL do CSV diário de focos do INPE."""
    if data is None:
        data = datetime.now(ZoneInfo("America/Sao_Paulo")).date() - timedelta(days=1)
    nome = f"focos_diario_br_{data:%Y%m%d}.csv"
    base = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil"
    return f"{base}/{nome}", nome


# ─── Conexão ───────────────────────────────────────────────────
def get_conexao():
    return psycopg.connect(**DB_CONFIG, row_factory=dict_row)


# ─── Download do CSV ───────────────────────────────────────────
def baixar_csv(url: str) -> pd.DataFrame:
    """Baixa o CSV do INPE e retorna um DataFrame pandas."""
    log.info(f"Baixando CSV: {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        conteudo = resp.read().decode("utf-8")
    df = pd.read_csv(StringIO(conteudo))
    log.info(f"CSV baixado: {len(df)} linhas, colunas: {list(df.columns)}")
    return df


def carregar_csv_local(caminho: str) -> pd.DataFrame:
    """Carrega CSV de arquivo local (para testes sem internet)."""
    log.info(f"Carregando CSV local: {caminho}")
    df = pd.read_csv(caminho)
    log.info(f"CSV carregado: {len(df)} linhas")
    return df


# ─── Limpeza e normalização ────────────────────────────────────
def limpar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza colunas, remove nulos críticos e converte tipos."""
    df.columns = [c.strip().lower() for c in df.columns]

    # Remove linhas sem coordenadas (sem geom não tem sentido inserir)
    antes = len(df)
    df = df.dropna(subset=["lat", "lon"])
    removidos = antes - len(df)
    if removidos:
        log.warning(f"Removidas {removidos} linhas sem coordenadas")

    # Converte data_hora_gmt para datetime com timezone
    df["data_hora_gmt"] = pd.to_datetime(
        df["data_hora_gmt"], format="%Y-%m-%d %H:%M:%S", utc=True, errors="coerce"
    )
    df = df.dropna(subset=["data_hora_gmt"])

    # Normaliza strings: strip + upper para campos geográficos
    for col in ["estado", "municipio", "bioma", "pais"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.upper()

    # Garante tipos numéricos
    for col in ["risco_fogo", "frp", "precipitacao", "numero_dias_sem_chuva"]:
        if col in df.columns:
            # O INPE usa -999 para indicar dado indisponível.
            df[col] = pd.to_numeric(df[col], errors="coerce").replace(-999, float("nan"))

    # Limpa id (strip)
    df["id"] = df["id"].astype(str).str.strip()

    log.info(f"DataFrame limpo: {len(df)} linhas válidas")
    return df


# ─── Inserção em lote ──────────────────────────────────────────
BATCH_SIZE = 5_000


def valor_numerico_ou_none(valor):
    return None if pd.isna(valor) else valor


def inserir_focos(df: pd.DataFrame, nome_arquivo: str) -> dict:
    """
    Insere os focos no PostGIS em lotes usando executemany do psycopg3.
    Usa ON CONFLICT (id_inpe) DO NOTHING para evitar duplicatas.
    A geometria é construída diretamente em SQL: ST_SetSRID(ST_MakePoint(lon, lat), 4326).

    Contagem de inseridos: comparamos o total de registros no banco antes e depois
    da carga — mais confiável do que rowcount em executemany com ON CONFLICT.
    """
    total = len(df)
    id_log = None

    try:
        with get_conexao() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM pdqflow.focos")
                total_antes = cur.fetchone()["n"]

                cur.execute(
                    """
                    INSERT INTO pdqflow.log_carga (arquivo, total_linhas)
                    VALUES (%s, %s) RETURNING id
                    """,
                    (nome_arquivo, total),
                )
                id_log = cur.fetchone()["id"]
                conn.commit()

                try:
                    n_lotes = (total + BATCH_SIZE - 1) // BATCH_SIZE
                    for idx, inicio in enumerate(range(0, total, BATCH_SIZE), start=1):
                        lote = df.iloc[inicio : inicio + BATCH_SIZE]
                        registros = [
                            (
                                str(row["id"]),
                                row["data_hora_gmt"].isoformat(),
                                row.get("satelite"),
                                row.get("municipio"),
                                row.get("estado"),
                                row.get("pais", "BRASIL"),
                                row.get("municipio_id"),
                                row.get("estado_id"),
                                valor_numerico_ou_none(row.get("numero_dias_sem_chuva")),
                                valor_numerico_ou_none(row.get("precipitacao")),
                                valor_numerico_ou_none(row.get("risco_fogo")),
                                row.get("bioma"),
                                valor_numerico_ou_none(row.get("frp")),
                                float(row["lon"]),
                                float(row["lat"]),
                            )
                            for _, row in lote.iterrows()
                        ]

                        cur.executemany(
                            """
                            INSERT INTO pdqflow.focos (
                                id_inpe, data_hora_gmt, satelite, municipio, estado,
                                pais, municipio_id, estado_id, numero_dias_sem_chuva,
                                precipitacao, risco_fogo, bioma, frp, geom
                            )
                            VALUES (
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s,
                                %s, %s, %s, %s,
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                            )
                            ON CONFLICT (id_inpe) DO NOTHING
                            """,
                            registros,
                        )
                        conn.commit()
                        log.info(f"Lote {idx}/{n_lotes} — {len(registros)} registros processados")

                    cur.execute("SELECT COUNT(*) AS n FROM pdqflow.focos")
                    total_depois = cur.fetchone()["n"]
                    inseridos = total_depois - total_antes
                    duplicados = total - inseridos

                    cur.execute(
                        """
                        UPDATE pdqflow.log_carga
                        SET inseridos = %s, duplicados = %s,
                            finalizado_em = NOW(), status = 'sucesso'
                        WHERE id = %s
                        """,
                        (inseridos, max(duplicados, 0), id_log),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
    except Exception:
        if id_log is not None:
            try:
                with get_conexao() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE pdqflow.log_carga
                            SET finalizado_em = NOW(), status = 'erro'
                            WHERE id = %s
                            """,
                            (id_log,),
                        )
                    conn.commit()
            except Exception:
                log.exception(f"Não foi possível registrar falha da carga {id_log}")
        raise

    log.info(
        f"Carga finalizada — Total CSV: {total} | "
        f"Inseridos: {inseridos} | Duplicados (ignorados): {max(duplicados, 0)}"
    )
    return {"total": total, "inseridos": inseridos, "duplicados": max(duplicados, 0)}


# ─── Verificação pós-carga com consultas PostGIS ───────────────
def verificar_carga():
    """Executa consultas de verificação que demonstram uso do PostGIS."""
    log.info("─── Verificação pós-carga ───────────────────────")
    with get_conexao() as conn:
        with conn.cursor() as cur:

            # 1. Total de focos
            cur.execute("SELECT COUNT(*) AS total FROM pdqflow.focos")
            total = cur.fetchone()["total"]
            log.info(f"Total de focos no banco: {total:,}")

            # 2. Focos por bioma (GROUP BY)
            cur.execute(
                "SELECT bioma, total_focos, risco_medio "
                "FROM pdqflow.vw_focos_por_bioma LIMIT 5"
            )
            for r in cur.fetchall():
                log.info(f"  Bioma {r['bioma']}: {r['total_focos']:,} focos | risco médio {r['risco_medio']}")

            # 3. Consulta espacial: focos a ≤ 50 km de Brasília
            # ST_DWithin com geografia calcula distância real em metros
            cur.execute(
                """
                SELECT COUNT(*) AS focos_prox_brasilia
                FROM pdqflow.focos
                WHERE ST_DWithin(
                    geom::geography,
                    ST_MakePoint(-47.9292, -15.7801)::geography,
                    50000   -- 50 km em metros
                )
                """
            )
            r = cur.fetchone()
            log.info(f"Focos num raio de 50 km de Brasília: {r['focos_prox_brasilia']}")

            # 4. Centróide geográfico da Amazônia (PostGIS ST_Centroid)
            cur.execute(
                """
                SELECT
                    ST_X(ST_Centroid(ST_Collect(geom))) AS lon_centroide,
                    ST_Y(ST_Centroid(ST_Collect(geom))) AS lat_centroide
                FROM pdqflow.focos
                WHERE bioma = 'AMAZÔNIA'
                """
            )
            r = cur.fetchone()
            if r and r["lon_centroide"]:
                log.info(
                    f"Centróide dos focos na Amazônia: "
                    f"lon={r['lon_centroide']:.4f}, lat={r['lat_centroide']:.4f}"
                )

    log.info("─────────────────────────────────────────────────")


# ─── Função principal de execução ─────────────────────────────
def executar_carga(csv_local: str | None = None):
    """
    Executa uma carga completa.
    - csv_local: caminho de arquivo CSV já baixado (para testes)
    - Se None, baixa o arquivo diário do dia anterior do INPE
    """
    log.info("=== PDQ-Flow ETL — Iniciando carga ===")
    try:
        if csv_local:
            df = carregar_csv_local(csv_local)
            nome_arquivo = os.path.basename(csv_local)
        else:
            url, nome_arquivo = url_inpe_diario()
            df = baixar_csv(url)

        df = limpar_dataframe(df)
        resultado = inserir_focos(df, nome_arquivo)
        verificar_carga()
        log.info(f"=== Carga concluída: {resultado} ===")
    except Exception as e:
        log.error(f"Erro durante a carga: {e}", exc_info=True)


# ─── Agendador (execução automática diária) ────────────────────
def iniciar_agendador():
    """
    Inicia o scheduler APScheduler.
    Executa a carga todo dia às 07:00 horário de Brasília, após a publicação
    do arquivo diário do INPE.
    """
    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        executar_carga,
        trigger="cron",
        hour=7,
        minute=0,
        id="carga_diaria_inpe",
        name="Carga diária INPE",
        misfire_grace_time=3600,  # aceita até 1h de atraso
    )
    log.info("Agendador iniciado — carga diária às 07:00 BRT")
    log.info("Executando carga inicial ao subir...")
    executar_carga()   # executa imediatamente ao iniciar o container
    scheduler.start()


# ─── Entrypoint ────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Modo manual: python carga.py caminho/arquivo.csv
        executar_carga(csv_local=sys.argv[1])
    else:
        # Modo agendado (padrão do container)
        iniciar_agendador()
