FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app

# Instala dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# config.py compartilhado pelos três serviços
COPY config.py .

# O código do serviço é montado via volume em /app/servico/
# Comando padrão — sobrescrito no docker-compose por serviço
CMD ["python", "/app/servico/servico.py"]
