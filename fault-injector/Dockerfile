FROM python:3.13-slim

WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]>=3.2,<4"
COPY exhaust_connections.py /app/exhaust_connections.py

CMD ["python", "-u", "/app/exhaust_connections.py"]
