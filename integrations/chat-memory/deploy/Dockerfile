# Cloud mode: runs the web MCP server against a clone of your PRIVATE vault repo.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir /app
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENV PORT=8765
EXPOSE 8765
ENTRYPOINT ["/entrypoint.sh"]
