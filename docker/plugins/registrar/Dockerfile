FROM local/noetl-plugin-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY ${PRJ_PATH}/noetl/playbook.py \
     ${PRJ_PATH}/noetl/registrar.py ./noetl/

CMD ["python", "/usr/noetl/noetl/registrar.py"]
