FROM local/noetl-plugin-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY    ${PRJ_PATH}/noetl/workflow.py \
        ${PRJ_PATH}/noetl/dispatcher.py ./

CMD ["python", "./dispatcher.py"]
