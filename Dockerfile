FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py openapi.yaml ./

RUN mkdir -p /app/data

EXPOSE 8091

ENV PORT=8091
ENV DATABASE_PATH=/app/data/users.db

CMD ["python", "app.py"]
