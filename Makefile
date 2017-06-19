# Disable make's implicit rules, which are not useful for golang, and slow down the build
# considerably.
.SUFFIXES:

SRC_FILES=$(shell find . -type f -name '*.go')

# These variables can be overridden by setting an environment variable.
LOCAL_IP_ENV?=$(shell ip route get 8.8.8.8 | head -1 |  awk '{print $$7}')

# Can choose different docker versions see list here - https://hub.docker.com/_/docker/
DOCKER_VERSION?=dind
HOST_CHECKOUT_DIR?=$(CURDIR)
CONTAINER_NAME?=calico/libnetwork-plugin
CALICO_BUILD?=calico/go-build
PLUGIN_LOCATION?=$(CURDIR)/dist/libnetwork-plugin
DOCKER_BINARY_CONTAINER?=docker-binary-container

# To run with non-native docker (e.g. on Windows or OSX) you might need to overide this variable
LOCAL_USER_ID?=$(shell id -u $$USER)

default: all
all: test

# Use this to populate the vendor directory after checking out the repository.
# To update upstream dependencies, delete the glide.lock file first.
vendor: glide.yaml
	# To build without Docker just run "glide install -strip-vendor"
	docker run --rm \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin:rw \
		-v $(HOME)/.glide:/home/user/.glide:rw \
		-e LOCAL_USER_ID=$(LOCAL_USER_ID) \
		$(CALICO_BUILD) /bin/sh -c ' \
			cd /go/src/github.com/projectcalico/libnetwork-plugin && \
			glide install -strip-vendor' 

install:
	CGO_ENABLED=0 go install github.com/projectcalico/libnetwork-plugin

# Run the build in a container. Useful for CI
dist/libnetwork-plugin: vendor
	-mkdir -p dist
	-mkdir -p .go-pkg-cache
	docker run --rm \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin:ro \
		-v $(CURDIR)/dist:/go/src/github.com/projectcalico/libnetwork-plugin/dist \
		-v $(CURDIR)/.go-pkg-cache:/go/pkg/:rw \
		-e LOCAL_USER_ID=$(LOCAL_USER_ID) \
		$(CALICO_BUILD) sh -c '\
			cd /go/src/github.com/projectcalico/libnetwork-plugin && \
			make build'

build: $(SRC_FILES) vendor
	CGO_ENABLED=0 go build -v -i -o dist/libnetwork-plugin -ldflags "-X main.VERSION=$(shell git describe --tags --dirty) -s -w" main.go

$(CONTAINER_NAME): dist/libnetwork-plugin
	docker build -t $(CONTAINER_NAME) .

# Perform static checks on the code. The golint checks are allowed to fail, the others must pass.
.PHONY: static-checks
static-checks: vendor
	docker run --rm \
		-e LOCAL_USER_ID=$(LOCAL_USER_ID) \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin \
		calico/go-build sh -c '\
			cd  /go/src/github.com/projectcalico/libnetwork-plugin && \
			gometalinter --deadline=30s --disable-all --enable=goimports --enable=vet --enable=errcheck --enable=varcheck --enable=unused --enable=dupl $$(glide nv)'

run-etcd:
	@-docker rm -f calico-etcd
	docker run --detach \
	--net=host \
	--name calico-etcd quay.io/coreos/etcd \
	etcd \
	--advertise-client-urls "http://$(LOCAL_IP_ENV):2379,http://127.0.0.1:2379" \
	--listen-client-urls "http://0.0.0.0:2379"

release: clean
ifndef VERSION
	$(error VERSION is undefined - run using make release VERSION=vX.Y.Z)
endif
	git tag $(VERSION)
	$(MAKE) $(CONTAINER_NAME) 
	# Check that the version output appears on a line of its own (the -x option to grep).
# Tests that the "git tag" makes it into the binary. Main point is to catch "-dirty" builds
	@echo "Checking if the tag made it into the binary"
	docker run --rm calico/libnetwork-plugin -v | grep -x $(VERSION) || (echo "Reported version:" `docker run --rm calico/libnetwork-plugin -v` "\nExpected version: $(VERSION)" && exit 1)
	docker tag calico/libnetwork-plugin calico/libnetwork-plugin:$(VERSION)
	docker tag calico/libnetwork-plugin quay.io/calico/libnetwork-plugin:$(VERSION)
	docker tag calico/libnetwork-plugin quay.io/calico/libnetwork-plugin:latest

	@echo "Now push the tag and images. Then create a release on Github and attach the dist/libnetwork-plugin binary"
	@echo "git push origin $(VERSION)"
	@echo "docker push calico/libnetwork-plugin:$(VERSION)"
	@echo "docker push quay.io/calico/libnetwork-plugin:$(VERSION)"
	@echo "docker push calico/libnetwork-plugin:latest"
	@echo "docker push quay.io/calico/libnetwork-plugin:latest"

clean:
	rm -rf dist *.tar vendor docker .go-pkg-cache

run-plugin: run-etcd dist/libnetwork-plugin
	-docker rm -f dind
	docker run -tid -h test --name dind --privileged $(ADDITIONAL_DIND_ARGS) \
		-e ETCD_ENDPOINTS=http://$(LOCAL_IP_ENV):2379 \
		-p 5375:2375 \
		-v $(PLUGIN_LOCATION):/libnetwork-plugin \
		docker:$(DOCKER_VERSION) --cluster-store=etcd://$(LOCAL_IP_ENV):2379
	# View the logs by running 'docker exec dind cat plugin.log'
	docker exec -tid --privileged dind sh -c '/libnetwork-plugin 2>>/plugin.log'
	# To speak to this docker:
	# export DOCKER_HOST=localhost:5375

.PHONY: test
# Run the unit tests.
test:
	CGO_ENABLED=0 ginkgo -v tests/*

test-containerized: dist/libnetwork-plugin
	-docker rm -f $(DOCKER_BINARY_CONTAINER) 2>&1
	docker create --name $(DOCKER_BINARY_CONTAINER) docker:$(DOCKER_VERSION)
	docker cp $(DOCKER_BINARY_CONTAINER):/usr/local/bin/docker .
	docker rm -f $(DOCKER_BINARY_CONTAINER)
	docker run -ti --rm --net=host \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v $(CURDIR)/docker:/usr/bin/docker	\
		-e PLUGIN_LOCATION=$(CURDIR)/dist/libnetwork-plugin \
		-e LOCAL_USER_ID=0 \
		calico/go-build sh -c '\
			cd  /go/src/github.com/projectcalico/libnetwork-plugin && \
			make test'

