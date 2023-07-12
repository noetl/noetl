FROM redis:latest

RUN apt-get update && apt-get install -y build-essential git curl

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

ENV PATH="/root/.cargo/bin:${PATH}"
ENV CARGO_HOME="/root/.cargo"
ENV RUSTUP_HOME="/root/.rustup"

WORKDIR /redisjson

RUN git clone https://github.com/RedisJSON/RedisJSON.git .

RUN make

CMD redis-server --loadmodule /redisjson/src/redisjson.so
