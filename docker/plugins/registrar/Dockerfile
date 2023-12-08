FROM local/noetl-plugin-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY  ${PRJ_PATH}/noetl/plugin.py \
      ${PRJ_PATH}/noetl/keyval.py \
      ${PRJ_PATH}/noetl/payload.py \
      ${PRJ_PATH}/noetl/natstream.py \
      ${PRJ_PATH}/noetl/registrar.py ./

CMD ["python", "./registrar.py"]
