FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy MCP server package
COPY mcp_server/ ./mcp_server/

# Copy Boros knowledge base
COPY boros-kb/ ./boros-kb/

# Cloud Run uses PORT env var (default 8080)
ENV PORT=8080

EXPOSE 8080

CMD ["python", "-m", "mcp_server", "--transport", "streamable-http"]
