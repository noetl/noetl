FROM eclipse-temurin:11-jre

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl openssl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ibkr

# Copy all gateway files
COPY bin/ /opt/ibkr/bin/
COPY build/ /opt/ibkr/build/
COPY dist/ /opt/ibkr/dist/
COPY root/ /opt/ibkr/root/

# Make scripts executable
RUN chmod +x /opt/ibkr/bin/*.sh

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -k -f https://localhost:5000/v1/api/iserver/auth/status || exit 1

CMD ["bash", "-c", "cd /opt/ibkr && ./bin/run.sh root/conf.api.alpha.yaml"]
