FROM python:3.12-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn

# Copy the test server
COPY tests/fixtures/servers/paginated_api.py /app/paginated_api.py

# Expose port
EXPOSE 5555

# Run the server
CMD ["python", "paginated_api.py", "5555"]
