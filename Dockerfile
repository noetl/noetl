FROM golang:1.11.1-alpine3.8 as builder

LABEL maintainer="NoETL"

WORKDIR /go/src/noetl

COPY . .

RUN apk --no-cache add ca-certificates shared-mime-info mailcap git build-base curl && \
    curl https://raw.githubusercontent.com/golang/dep/master/install.sh | sh

RUN make

# Second stage
FROM alpine:3.8

RUN addgroup -S noetl && \
    adduser -S -G noetl noetl

COPY --from=builder /go/src/noetl/noetl /home/noetl/

RUN chown -R noetl:noetl /home/noetl

USER noetl

ENTRYPOINT ["/home/noetl/noetl"]