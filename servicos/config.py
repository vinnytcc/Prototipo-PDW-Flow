"""
PDQ-Flow v1.0 — Configuração compartilhada dos serviços
========================================================
Importado por focos/servico.py, espacial/servico.py e estatisticas/servico.py
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Identificação do projeto ─────────────────────────────────
DESCRICAO_APP = "PDQ-Flow — Pipeline de Dados sobre Queimadas"
VERSAO        = "1.0"

# ─── Conexão com o banco ──────────────────────────────────────
DB_CONFIG = dict(
    host     = os.getenv("DB_HOST",     "banco"),
    port     = int(os.getenv("DB_PORT", 5432)),
    user     = os.getenv("DB_USER",     "pdqflow"),
    password = os.getenv("DB_PASSWORD", "pdqflow123"),
    dbname   = os.getenv("DB_NAME",     "queimadas"),
)
