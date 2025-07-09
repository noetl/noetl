# /docker/noetl/development/Dockerfile

# --- Builder Stage ---
# This stage now only installs Python dependencies.
FROM python:3.12-slim AS builder

# Install uv, the fast package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install only Python build dependencies
RUN apt-get update && apt-get --no-install-recommends install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/noetl

# Copy Python project files
COPY pyproject.toml ./
COPY uv.lock* ./

# Create a virtual environment and install Python packages
RUN uv venv && \
    uv sync --frozen --no-dev --no-install-project

# Copy the entire noetl package, which now INCLUDES the pre-built UI
# from the build_ui.sh script.
COPY noetl ./noetl

# Copy other project files
COPY LICENSE README.md ./

# Install the noetl package itself
RUN uv pip install -e .


# --- Production Stage ---
# This stage creates the final, lean image.
FROM python:3.12-slim AS production

# Install only necessary runtime dependencies
RUN apt-get update && apt-get --no-install-recommends install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Chicago
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy the virtual environment from the builder
COPY --from=builder /opt/noetl/.venv /opt/noetl/.venv

WORKDIR /opt/noetl

# Copy the entire application source, including the pre-built UI
COPY --from=builder /opt/noetl/noetl ./noetl
COPY --from=builder /opt/noetl/pyproject.toml ./
COPY --from=builder /opt/noetl/LICENSE ./
COPY --from=builder /opt/noetl/README.md ./

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/opt/noetl:$PYTHONPATH"
ENV PATH="/opt/noetl/.venv/bin:$PATH"

EXPOSE 8080

# The command to run the application
CMD ["python", "-m", "uvicorn", "noetl.main:create_app", "--host", "0.0.0.0", "--port", "8080"]
