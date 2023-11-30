FROM local/noetl-api-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY  ${PRJ_PATH}/noetl/config.py \
      ${PRJ_PATH}/noetl/keyval.py \
      ${PRJ_PATH}/noetl/api.py \
      ${PRJ_PATH}/noetl/gql.py \
      ${PRJ_PATH}/noetl/natstream.py \
      ${PRJ_PATH}/noetl/payload.py ./

EXPOSE 8021

CMD ["python", "./api.py"]
