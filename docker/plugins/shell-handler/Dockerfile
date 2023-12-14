FROM local/noetl-plugin-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY  ${PRJ_PATH}/noetl/shell_handler.py ./

CMD ["python", "./shell_handler.py"]
