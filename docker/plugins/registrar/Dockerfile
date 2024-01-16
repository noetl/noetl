FROM local/noetl-plugin-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY ${PRJ_PATH}/noetl/plugins/__init__.py \
     ${PRJ_PATH}/noetl/playbook.py \
     ${PRJ_PATH}/noetl/plugins/registrar.py ./noetl/plugins/

CMD ["python", "/usr/noetl/noetl/plugins/registrar.py"]
