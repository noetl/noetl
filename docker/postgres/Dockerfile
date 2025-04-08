FROM postgres:17.4

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        postgresql-plpython3-14 \
        python3-pip \
        python3-setuptools \
        python3-dev \
        tzdata && \
    pip3 install --upgrade pip --break-system-packages && \
    pip3 install Jinja2 --break-system-packages && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV TZ=America/Chicago
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
COPY ./docker/postgres/postgresql.conf /etc/postgresql/postgresql.conf
COPY ./data/noetldb/init_noetldb.sh /docker-entrypoint-initdb.d/init_noetldb.sh
COPY ./data/noetldb/noetldb_ddl.sql /noetldb_ddl.sql