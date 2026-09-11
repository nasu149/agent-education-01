FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
ENV PYTHONPATH=/app/src
RUN mkdir -p /app/logs

EXPOSE 8090
CMD ["uvicorn", "agent.api:app", "--host", "0.0.0.0", "--port", "8090"]
