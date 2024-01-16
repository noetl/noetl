FROM local/noetl-api-base:latest
ARG PRJ_PATH
WORKDIR /usr/noetl

COPY  ${PRJ_PATH}/noetl/api/__init__.py \
      ${PRJ_PATH}/noetl/api/app.py \
      ${PRJ_PATH}/noetl/api/config.py \
      ${PRJ_PATH}/noetl/api/resolvers.py ./noetl/api/

ENV PYTHONPATH=/usr/noetl

EXPOSE 8021

CMD ["python", "/usr/noetl/noetl/api/app.py"]
