FROM python:3.11-slim

WORKDIR /app

RUN useradd --create-home --shell /bin/bash appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

ENV DATA_DIR=/app/data

CMD ["python", "-u", "bot.py"]
