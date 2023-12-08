FROM local/noetl-plugin-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY  ${PRJ_PATH}/noetl/plugin.py \
      ${PRJ_PATH}/noetl/keyval.py \
      ${PRJ_PATH}/noetl/payload.py \
      ${PRJ_PATH}/noetl/natstream.py \
      ${PRJ_PATH}/noetl/dispatcher.py ./

CMD ["python", "./dispatcher.py"]
