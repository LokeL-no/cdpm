FROM python:3.12-slim

WORKDIR /app

# Installer avhengigheter
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopier bot-koden
COPY web_bot_multi.py .
COPY arbitrage_strategy.py .
COPY spread_engine.py .
COPY execution_simulator.py .

# Eksponér WebSocket-porten
EXPOSE 8080

# Kjør botten
CMD ["python3", "web_bot_multi.py"]
