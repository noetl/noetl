FROM local/noetl-plugin-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY ${PRJ_PATH}/noetl/registrar.py ./

CMD ["python", "./registrar.py"]
