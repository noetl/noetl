CODE = app
VENV = .venv
PYTHON_BIN = $(VENV)/bin/python
DIR = $(realpath .)

.PHONY: run, noetl-build, noetl-start, noetl, redis-build, redis-start, redis-stop, redis-restart
run: stop start log

build:
	docker-compose -f docker-compose.yaml build


start:
	docker-compose -f docker-compose.yaml up -d --remove-orphans

log:
	docker-compose logs --tail 1000 --follow workflow_engine

stop:
	docker-compose stop

destroy:
	docker-compose down

init:
	brew ls --versions pyenv || brew install pyenv
	brew ls --versions redis || brew install redis
	if [ ! -d $(VENV) ]; then python -m venv .venv; fi
	$(PYTHON_BIN) -m pip install --upgrade pip && \
	. $(VENV)/bin/activate && \
	$(VENV)/bin/pip install -r requirements.txt

noetl-build:
	docker-compose build noetl

noetl-start:
	docker-compose up --detach noetl


redis-build:
	docker-compose build noetldb

redis-start:
	docker-compose up --detach noetldb

redis-stop:
	docker-compose stop noetldb

redis-restart:
	docker-compose restart noetldb


noetl:
	source $(VENV)/bin/activate &&
    DEBUG=0 \
    HOST=localhost \
    LOG_LEVEL=info \
    ENV=development \
    REDIS_HOST=localhost \
    REDIS_KEY_TTL=10800 \
    REDIS_PORT=6379 \
    REFRESH_FREQUENCY=10 \
    RELOAD=0 \
    WORKERS=0 \
	time $(PBIN) src/noetl.py > noetl.log 2>&1
