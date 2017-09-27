##############################################################################
# The build architecture is select by setting the ARCH variable.
# For example: When building on ppc64le you could use ARCH=ppc64le make <....>.
# When ARCH is undefined it defaults to amd64.
ARCH?=amd64
ifeq ($(ARCH),amd64)
	ARCHTAG:=
	GO_BUILD_VER?=v0.9
	BUSYBOX_IMAGE?=busybox:latest
	DIND_IMAGE?=docker:dind
endif

ifeq ($(ARCH),ppc64le)
	ARCHTAG:=-ppc64le
	GO_BUILD_VER?=latest
	BUSYBOX_IMAGE?=ppc64le/busybox:latest
	DIND_IMAGE?=ppc64le/docker:dind
endif

# Disable make's implicit rules, which are not useful for golang, and slow down the build
# considerably.
.SUFFIXES:

SRC_FILES=$(shell find . -type f -name '*.go')

# These variables can be overridden by setting an environment variable.
LOCAL_IP_ENV?=$(shell ip route get 8.8.8.8 | head -1 |  awk '{print $$7}')

# Can choose different docker versions see list here - https://hub.docker.com/_/docker/
DOCKER_VERSION?=dind
HOST_CHECKOUT_DIR?=$(CURDIR)
CONTAINER_NAME?=calico/libnetwork-plugin$(ARCHTAG)
GO_BUILD_CONTAINER?=calico/go-build$(ARCHTAG):$(GO_BUILD_VER)
PLUGIN_LOCATION?=$(CURDIR)/dist/libnetwork-plugin-$(ARCH)
DOCKER_BINARY_CONTAINER?=docker-binary-container$(ARCHTAG)

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
		$(GO_BUILD_CONTAINER) /bin/sh -c ' \
			cd /go/src/github.com/projectcalico/libnetwork-plugin && \
			glide install -strip-vendor' 

install:
	CGO_ENABLED=0 go install github.com/projectcalico/libnetwork-plugin

# Run the build in a container. Useful for CI
dist/libnetwork-plugin:dist/libnetwork-plugin-$(ARCH)
dist/libnetwork-plugin-$(ARCH): vendor
	-mkdir -p dist
	-mkdir -p .go-pkg-cache
	docker run --rm \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin:ro \
		-v $(CURDIR)/dist:/go/src/github.com/projectcalico/libnetwork-plugin/dist \
		-v $(CURDIR)/.go-pkg-cache:/go/pkg/:rw \
		-e LOCAL_USER_ID=$(LOCAL_USER_ID) \
		-e ARCH=$(ARCH) \
		$(GO_BUILD_CONTAINER) sh -c '\
			cd /go/src/github.com/projectcalico/libnetwork-plugin && \
			make build'

build: $(SRC_FILES) vendor
	CGO_ENABLED=0 go build -v -i -o dist/libnetwork-plugin-$(ARCH) -ldflags "-X main.VERSION=$(shell git describe --tags --dirty) -s -w" main.go


$(CONTAINER_NAME): dist/libnetwork-plugin-$(ARCH)
	docker build -t $(CONTAINER_NAME) -f Dockerfile$(ARCHTAG) .

# Perform static checks on the code. The golint checks are allowed to fail, the others must pass.
.PHONY: static-checks
static-checks: vendor
	docker run --rm \
		-e LOCAL_USER_ID=$(LOCAL_USER_ID) \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin \
		$(GO_BUILD_CONTAINER) sh -c '\
			cd  /go/src/github.com/projectcalico/libnetwork-plugin && \
			gometalinter --deadline=30s --disable-all --enable=goimports --enable=vet --enable=errcheck --enable=varcheck --enable=unused --enable=dupl $$(glide nv)'

run-etcd:
	@-docker rm -f calico-etcd
	docker run --detach \
	--net=host \
	--name calico-etcd quay.io/coreos/etcd:v3.2.5$(ARCHTAG) \
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
	docker run --rm calico/libnetwork-plugin$(ARCHTAG) -v | grep -x $(VERSION) || (echo "Reported version:" `docker run --rm calico/libnetwork-plugin$(ARCHTAG) -v` "\nExpected version: $(VERSION)" && exit 1)
	docker tag calico/libnetwork-plugin$(ARCHTAG) calico/libnetwork-plugin$(ARCHTAG):$(VERSION)
	docker tag calico/libnetwork-plugin$(ARCHTAG) quay.io/calico/libnetwork-plugin$(ARCHTAG):$(VERSION)
	docker tag calico/libnetwork-plugin$(ARCHTAG) quay.io/calico/libnetwork-plugin$(ARCHTAG):latest

	@echo "Now push the tag and images. Then create a release on Github and attach the dist/libnetwork-plugin binary"
	@echo "git push origin $(VERSION)"
	@echo "docker push calico/libnetwork-plugin$(ARCHTAG):$(VERSION)"
	@echo "docker push quay.io/calico/libnetwork-plugin$(ARCHTAG):$(VERSION)"
	@echo "docker push calico/libnetwork-plugin$(ARCHTAG):latest"
	@echo "docker push quay.io/calico/libnetwork-plugin$(ARCHTAG):latest"

clean:
	rm -rf dist *.tar vendor .go-pkg-cache

run-plugin: run-etcd dist/libnetwork-plugin-$(ARCH)
	-docker rm -f dind
	docker run -tid -h test --name dind --privileged $(ADDITIONAL_DIND_ARGS) \
		-e ETCD_ENDPOINTS=http://$(LOCAL_IP_ENV):2379 \
		-p 5375:2375 \
		-v $(PLUGIN_LOCATION):/libnetwork-plugin \
		$(DIND_IMAGE) --cluster-store=etcd://$(LOCAL_IP_ENV):2379
	# View the logs by running 'docker exec dind cat plugin.log'
	docker exec -tid --privileged dind sh -c 'sysctl -w net.ipv6.conf.default.disable_ipv6=0'
	docker exec -tid --privileged dind sh -c '/libnetwork-plugin 2>>/plugin.log'
	# To speak to this docker:
	# export DOCKER_HOST=localhost:5375

.PHONY: test
# Run the unit tests.
test:
	CGO_ENABLED=0 ginkgo -v tests/*

# Target test-containerized needs the docker binary to be available in the go-build container.
# Obtaining it from the docker:dind images docker should provided the latest version.  However,
# this assumes that the go_build container has the required dependencies or that docker is static.
# This may not be the case in all configurations. In this cases you should pre-populate ./bin
# with a docker binary compatible with the go-build image that is used.
bin/docker:
	-docker rm -f $(DOCKER_BINARY_CONTAINER) 2>&1
	mkdir -p ./bin
	docker create --name $(DOCKER_BINARY_CONTAINER) docker:$(DOCKER_VERSION)
	docker cp $(DOCKER_BINARY_CONTAINER):/usr/local/bin/docker ./bin/docker
	docker rm -f $(DOCKER_BINARY_CONTAINER)

test-containerized: dist/libnetwork-plugin-$(ARCH) bin/docker
	docker run -t --rm --net=host \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v $(CURDIR)/bin/docker:/usr/bin/docker \
		-e PLUGIN_LOCATION=$(CURDIR)/dist/libnetwork-plugin-$(ARCH) \
		-e LOCAL_USER_ID=0 \
		-e ARCH=$(ARCH) \
		-e BUSYBOX_IMAGE=$(BUSYBOX_IMAGE) \
		$(GO_BUILD_CONTAINER) sh -c '\
			cd  /go/src/github.com/projectcalico/libnetwork-plugin && \
			make test'

