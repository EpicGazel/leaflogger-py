FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY schema.sql .
COPY src/ ./src/
ENV PYTHONPATH=/app/src LEAFLOGGER_DB=/data/leaflogger.db
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "leaflogger.app:app", "--host", "0.0.0.0", "--port", "8000"]
