
GOCMD=go
GOBUILD=$(GOCMD) build
GOCLEAN=$(GOCMD) clean
GOTEST=$(GOCMD) test
BINARY_NAME=noetl
BINARY_UNIX=$(BINARY_NAME)_unix

# Docker
TAG = 0.1.0
IMAGE_NAME = noetl
REGISTRY = antonputra
REPO = noetl

all: deps build

docker: build-image push-image clean-image

exec:
	$(GOCMD) run main.go

build: 
	$(GOBUILD) -o $(BINARY_NAME) main.go

test: 
	$(GOTEST) -v ./...

clean: 
	$(GOCLEAN)
	rm -f $(BINARY_NAME)
	rm -f $(BINARY_UNIX)

deps:
	dep ensure

build-image:
	docker build -t $(REGISTRY)/$(REPO)/$(IMAGE_NAME) -f Dockerfile .
	docker tag $(REGISTRY)/$(REPO)/$(IMAGE_NAME) $(REGISTRY)/$(REPO)/$(IMAGE_NAME):$(TAG)

push-image:
	docker push $(REGISTRY)/$(REPO)/$(IMAGE_NAME)
	docker push $(REGISTRY)/$(REPO)/$(IMAGE_NAME):$(TAG)

clean-image:
	docker rmi $(REGISTRY)/$(REPO)/$(IMAGE_NAME):$(TAG) || :
	docker rmi $(REGISTRY)/$(REPO)/$(IMAGE_NAME) || :

# Cross compilation
build-linux:
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 $(GOBUILD) -o $(BINARY_UNIX) -v
docker-build:
	docker run --rm -it -v "$(GOPATH)":/go -w /go/src/bitbucket.org/rsohlich/makepost golang:latest go build -o "$(BINARY_UNIX)" -v

# build:
# 	swagger generate server -f swagger.yml
# 	docker build -t dataparser .

run:
	docker run -p 8888:8888 $(REGISTRY)/$(REPO)/$(IMAGE_NAME):$(TAG)

deploy:
	kubectl apply -f deployment/