FROM local/noetl-plugin-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY  ${PRJ_PATH}/noetl/http_handler.py ./noetl/

ENV PYTHONPATH=/usr/noetl
CMD ["python", "/usr/noetl/noetl/http_handler.py"]
