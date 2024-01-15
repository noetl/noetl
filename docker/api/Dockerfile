FROM local/noetl-api-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY  ${PRJ_PATH}/noetl/api.py \
      ${PRJ_PATH}/noetl/api_config.py \
      ${PRJ_PATH}/noetl/api_resolvers.py ./

EXPOSE 8021

CMD ["python", "./api.py"]
