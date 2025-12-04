FROM postgres:16-alpine

# Install bash and postgresql client utilities
RUN apk add --no-cache \
    bash \
    postgresql-client \
    curl \
    jq

# Create workspace directory for scripts
RUN mkdir -p /workspace

# Set working directory
WORKDIR /workspace

# Copy all scripts and SQL files into the image
COPY scripts/*.sh /workspace/
COPY sql/*.sql /workspace/

# Make all shell scripts executable
RUN chmod +x /workspace/*.sh

# Add execution permissions helper script
RUN echo '#!/bin/bash' > /usr/local/bin/ensure-executable.sh && \
    echo 'chmod +x /workspace/*.sh 2>/dev/null || true' >> /usr/local/bin/ensure-executable.sh && \
    chmod +x /usr/local/bin/ensure-executable.sh

# Default shell
SHELL ["/bin/bash", "-c"]

# Label for identification
LABEL org.noetl.image.type="container-test" \
      org.noetl.image.purpose="postgres-initialization" \
      org.noetl.image.version="1.0.0"

# Health check to verify psql is available
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD psql --version || exit 1

# Default command - will be overridden by playbook
CMD ["/bin/bash"]
