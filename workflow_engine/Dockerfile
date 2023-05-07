FROM python:3.11.3
RUN apt-get update \
    && apt-get --no-install-recommends install -y build-essential libssl-dev libffi-dev cargo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH "${PYTHONPATH}:/usr/src"

RUN  apt-get update \
     && apt-get -y install curl \
     && apt-get -y install wget


COPY ./requirements.txt /usr/workflow_engine/requirements.txt
COPY ./src/* /usr/workflow_engine/


RUN pip install --upgrade pip setuptools wheel \
    && pip install -r /usr/workflow_engine/requirements.txt \
    && rm -rf /root/.cache/pip
