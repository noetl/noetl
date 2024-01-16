FROM local/noetl-plugin-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY  ${PRJ_PATH}/noetl/plugins/__init__.py \
      ${PRJ_PATH}/noetl/plugins/http_handler.py ./noetl/plugins/

ENV PYTHONPATH=/usr/noetl
CMD ["python", "/usr/noetl/noetl/plugins/http_handler.py"]
