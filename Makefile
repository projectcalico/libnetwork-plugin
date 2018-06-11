###############################################################################
# Both native and cross architecture builds are supported.
# The target architecture is select by setting the ARCH variable.
# When ARCH is undefined it is set to the detected host architecture.
# When ARCH differs from the host architecture a crossbuild will be performed.
ARCHES=$(patsubst Dockerfile.%,%,$(wildcard Dockerfile.*))

# BUILDARCH is the host architecture
# ARCH is the target architecture
# we need to keep track of them separately
BUILDARCH ?= $(shell uname -m)
BUILDOS ?= $(shell uname -s | tr A-Z a-z)

# canonicalized names for host architecture
ifeq ($(BUILDARCH),aarch64)
	BUILDARCH=arm64
endif
ifeq ($(BUILDARCH),x86_64)
	BUILDARCH=amd64
endif

# unless otherwise set, I am building for my own architecture, i.e. not cross-compiling
ARCH ?= $(BUILDARCH)

# canonicalized names for target architecture
ifeq ($(ARCH),aarch64)
	override ARCH=arm64
endif
ifeq ($(ARCH),x86_64)
	override ARCH=amd64
endif

GO_BUILD_VER ?= v0.15
# for building, we use the go-build image for the *host* architecture, even if the target is different
# the one for the host should contain all the necessary cross-compilation tools.
# cross-compilation is only supported on amd64.
GO_BUILD_CONTAINER ?= calico/go-build:$(GO_BUILD_VER)-$(BUILDARCH)

# quay.io not following naming convention for amd64 images.
ifeq ($(BUILDARCH),amd64)
        ETCD_IMAGE ?= quay.io/coreos/etcd:v3.2.5
else
	ETCD_IMAGE ?= quay.io/coreos/etcd:v3.2.5-$(BUILDARCH)
endif

BUSYBOX_IMAGE_VERSION ?= latest
BUSYBOX_IMAGE ?= $(BUILDARCH)/busybox:$(BUSYBOX_IMAGE_VERSION)

DIND_IMAGE_VERSION ?= 17.12.0-dind
DIND_IMAGE ?= $(BUILDARCH)/docker:$(DIND_IMAGE_VERSION)

# Disable make's implicit rules, which are not useful for golang, and slow down the build
# considerably.
.SUFFIXES:

SRC_FILES=$(shell find . -type f -name '*.go')

# These variables can be overridden by setting an environment variable.
LOCAL_IP_ENV?=$(shell ip route get 8.8.8.8 | head -1 |  awk '{print $$7}')

# Can choose different docker versions see list here - https://hub.docker.com/_/docker/
HOST_CHECKOUT_DIR?=$(CURDIR)
CONTAINER_NAME?=calico/libnetwork-plugin
PLUGIN_LOCATION?=$(CURDIR)/dist/libnetwork-plugin-$(ARCH)

# To run with non-native docker (e.g. on Windows or OSX) you might need to overide this variable
LOCAL_USER_ID?=$(shell id -u $$USER)

help:
	@echo "Makefile for libnetwork-plugin."
	@echo 
	@echo "For any target, set ARCH=<target> to build for a given target."
	@echo "For example, to build for arm64:"
	@echo
	@echo "  make image ARCH=arm64"
	@echo
	@echo "Builds:"
	@echo "  make build  	Run the build in a container for the current docker OS and ARCH."
	@echo "  make build-all Run the build in a container for all archs"
	@echo "  make image	Build the calico/libnetwork-plugin image."
	@echo "  make image-all Build the calico/libnetwork-plugin image for all archs."
	@echo "  make all	Builds the image and runs tests."
	@echo
	@echo "Tests:"
	@echo "  make test-containerized	Run tests in a container"
	@echo
	@echo "Maintenance:"
	@echo "  make clean         Remove binary files."
	@echo "  make help	    Display this help text."
	@echo "-----------------------------------------"
	@echo "ARCH (target):		$(ARCH)"
	@echo "BUILDARCH (host):	$(BUILDARCH)"
	@echo "GO_BUILD_CONTAINER:	$(GO_BUILD_CONTAINER)"
	@echo "BUSYBOX_IMAGE:		$(BUSYBOX_IMAGE)"
	@echo "DIND_IMAGE:		$(DIND_IMAGE)"
	@echo "ETCDIMAGE:		$(ETCDIMAGE)"
	@echo "-----------------------------------------"

default: all
all: image test-containerized

# Use this to populate the vendor directory after checking out the repository.
# To update upstream dependencies, delete the glide.lock file first.
vendor: glide.yaml
	# Ensure that the glide cache directory exists.
	mkdir -p $(HOME)/.glide

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

###############################################################################
# Building the binary
###############################################################################
build: dist/libnetwork-plugin-$(ARCH)
build-all: $(addprefix sub-build-,$(ARCHES))
sub-build-%:
	$(MAKE) build ARCH=$*

# Run the build in a container. Useful for CI
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
			make binary'

binary: $(SRC_FILES) vendor
	CGO_ENABLED=0 GOARCH=$(ARCH) go build -v -i -o dist/libnetwork-plugin-$(ARCH) -ldflags "-X main.VERSION=$(shell git describe --tags --dirty) -s -w" main.go

###############################################################################
# Building the image
###############################################################################
image: image.created-$(ARCH)
image-all: $(addprefix sub-image-,$(ARCHES))
sub-image-%:
	$(MAKE) image ARCH=$*

image.created-$(ARCH): dist/libnetwork-plugin-$(ARCH)
	docker build -t $(CONTAINER_NAME):latest-$(ARCH) -f Dockerfile.$(ARCH) .
ifeq ($(ARCH),amd64)
	# Need amd64 builds tagged as :latest because Semaphore depends on that
	docker tag $(CONTAINER_NAME):latest-$(ARCH) $(CONTAINER_NAME):latest
endif
	touch $@

# ensure we have a real imagetag
imagetag:
ifndef IMAGETAG
	$(error IMAGETAG is undefined - run using make <target> IMAGETAG=X.Y.Z)
endif

###############################################################################
# tag and push images of any tag
###############################################################################

## push all arches
push-all: imagetag $(addprefix sub-push-,$(ARCHES))
sub-push-%:
	$(MAKE) push ARCH=$* IMAGETAG=$(IMAGETAG)

## push one arch
push: imagetag
	docker push $(CONTAINER_NAME):$(IMAGETAG)-$(ARCH)
	docker push quay.io/$(CONTAINER_NAME):$(IMAGETAG)-$(ARCH)
ifeq ($(ARCH),amd64)
	docker push $(CONTAINER_NAME):$(IMAGETAG)
	docker push quay.io/$(CONTAINER_NAME):$(IMAGETAG)
endif

## tag images of one arch
tag-images: imagetag
	docker tag $(CONTAINER_NAME):latest-$(ARCH) $(CONTAINER_NAME):$(IMAGETAG)-$(ARCH)
	docker tag $(CONTAINER_NAME):latest-$(ARCH) quay.io/$(CONTAINER_NAME):$(IMAGETAG)-$(ARCH)
ifeq ($(ARCH),amd64)
	docker tag $(CONTAINER_NAME):latest-$(ARCH) $(CONTAINER_NAME):$(IMAGETAG)
	docker tag $(CONTAINER_NAME):latest-$(ARCH) quay.io/$(CONTAINER_NAME):$(IMAGETAG)
endif

## tag images of all archs
tag-images-all: imagetag $(addprefix sub-tag-images-,$(ARCHES))
sub-tag-images-%:
	$(MAKE) tag-images ARCH=$* IMAGETAG=$(IMAGETAG)

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
	--name calico-etcd $(ETCD_IMAGE) \
	etcd \
	--advertise-client-urls "http://$(LOCAL_IP_ENV):2379,http://127.0.0.1:2379" \
	--listen-client-urls "http://0.0.0.0:2379"

###############################################################################
# Release
###############################################################################
release: clean
ifndef VERSION
	$(error VERSION is undefined - run using make release VERSION=vX.Y.Z)
endif
	git tag $(VERSION)
	$(MAKE) image
	$(MAKE) tag-images IMAGETAG=$(VERSION)
	# Generate the `latest` images.
	$(MAKE) tag-images IMAGETAG=latest

	# Check that the version output appears on a line of its own (the -x option to grep).
	# Tests that the "git tag" makes it into the binary. Main point is to catch "-dirty" builds
	@echo "Checking if the tag made it into the binary"
	docker run --rm $(CONTAINER_NAME):$(VERSION) -v | grep -x $(VERSION) || (echo "Reported version:" `docker run --rm $(CONTAINER_NAME):$(VERSION) -v` "\nExpected version: $(VERSION)" && exit 1)

	@echo "Now push the tag and images. Then create a release on Github and attach the dist/libnetwork-plugin binary"
	@echo "git push origin $(VERSION)"

	# Push images.
	$(MAKE) push IMAGETAG=$(VERSION) ARCH=$(ARCH)

clean:
	rm -rf dist image.created-*
	-docker rmi $(CONTAINER_NAME)

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

test-containerized: dist/libnetwork-plugin-$(ARCH)
ifeq ($(BUILDARCH),$(ARCH))
	docker run -t --rm --net=host \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-e PLUGIN_LOCATION=$(CURDIR)/dist/libnetwork-plugin-$(ARCH) \
		-e LOCAL_USER_ID=0 \
		-e ARCH=$(ARCH) \
		-e BUSYBOX_IMAGE=$(BUSYBOX_IMAGE) \
		$(GO_BUILD_CONTAINER) sh -c '\
			cd  /go/src/github.com/projectcalico/libnetwork-plugin && \
			make test'
else
	@echo Test-containerized is not supported when cross building.
endif
