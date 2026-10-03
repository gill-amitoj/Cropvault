FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# -u: unbuffered, so log lines show up in `docker compose logs` immediately
CMD ["python", "-u", "watcher.py"]
