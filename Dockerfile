FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py openapi.yaml ./

EXPOSE 8091

ENV PORT=8091

CMD ["python", "app.py"]
