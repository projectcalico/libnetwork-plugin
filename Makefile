# Disable make's implicit rules, which are not useful for golang, and slow down the build
# considerably.
.SUFFIXES:

SRC_FILES=$(shell find . -type f -name '*.go')

# These variables can be overridden by setting an environment variable.
LOCAL_IP_ENV?=$(shell ip route get 8.8.8.8 | head -1 |  awk '{print $$7}')

# Can choose different docker versions see list here - https://hub.docker.com/_/docker/
DOCKER_VERSION?=rc-dind
HOST_CHECKOUT_DIR?=$(CURDIR)
CONTAINER_NAME?=calico/libnetwork-plugin
CALICO_BUILD?=calico/go-build
default: all
all: test

# Use this to populate the vendor directory after checking out the repository.
# To update upstream dependencies, delete the glide.lock file first.
vendor: glide.yaml
	# To build without Docker just run "glide install -strip-vendor"
	docker run --rm \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin:rw \
		-v $(HOME)/.glide:/home/user/.glide:rw \
		-e LOCAL_USER_ID=`id -u $$USER` \
		$(CALICO_BUILD) /bin/sh -c ' \
			cd /go/src/github.com/projectcalico/libnetwork-plugin && \
			glide install -strip-vendor' 

install:
	CGO_ENABLED=0 go install github.com/projectcalico/libnetwork-plugin

# Run the build in a container. Useful for CI
dist/libnetwork-plugin: vendor
	-mkdir -p dist
	docker run --rm \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin:ro \
		-v $(CURDIR)/dist:/go/src/github.com/projectcalico/libnetwork-plugin/dist \
		-e LOCAL_USER_ID=`id -u $$USER` \
		$(CALICO_BUILD) sh -c '\
			cd /go/src/github.com/projectcalico/libnetwork-plugin && \
			make build'

build: $(SRC_FILES) vendor
	CGO_ENABLED=0 go build -v -o dist/libnetwork-plugin -ldflags "-X main.VERSION=$(shell git describe --tags --dirty) -s -w" main.go

$(CONTAINER_NAME): dist/libnetwork-plugin
	docker build -t $(CONTAINER_NAME) .

# Perform static checks on the code. The golint checks are allowed to fail, the others must pass.
.PHONY: static-checks
static-checks: vendor
	docker run --rm \
		-e LOCAL_USER_ID=`id -u $$USER` \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin \
		calico/go-build sh -c '\
			cd  /go/src/github.com/projectcalico/libnetwork-plugin && \
			gometalinter --deadline=30s --disable-all --enable=goimports --enable=vet --enable=errcheck --enable=varcheck --enable=unused --enable=dupl $$(glide nv)'

run-etcd:
	@-docker rm -f calico-etcd calico-etcd-ssl
	docker run --detach \
	--net=host \
	--name calico-etcd quay.io/coreos/etcd \
	etcd \
	--advertise-client-urls "http://$(LOCAL_IP_ENV):2379,http://127.0.0.1:2379" \
	--listen-client-urls "http://0.0.0.0:2379"

semaphore: test-containerized
	set -e; \
	if [ -z $$PULL_REQUEST_NUMBER ]; then \
		$(MAKE) $(CONTAINER_NAME); \
		docker tag $(CONTAINER_NAME) $(CONTAINER_NAME):$$BRANCH_NAME && docker push $(CONTAINER_NAME):$$BRANCH_NAME; \
		docker tag $(CONTAINER_NAME) quay.io/$(CONTAINER_NAME):$$BRANCH_NAME && docker push quay.io/$(CONTAINER_NAME):$$BRANCH_NAME; \
		if [ "$$BRANCH_NAME" = "master" ]; then \
			export VERSION=`git describe --tags --dirty`; \
			docker tag $(CONTAINER_NAME) $(CONTAINER_NAME):$$VERSION && docker push $(CONTAINER_NAME):$$VERSION; \
			docker tag $(CONTAINER_NAME) quay.io/$(CONTAINER_NAME):$$VERSION && docker push quay.io/$(CONTAINER_NAME):$$VERSION; \
		fi; \
	fi

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
	rm -rf dist *.tar vendor docker

run-plugin: run-etcd dist/libnetwork-plugin
	-docker rm -f dind
	docker run -h test --name dind --privileged -e ETCD_ENDPOINTS=http://$(LOCAL_IP_ENV):2379 -p 5375:2375 -d -v $(CURDIR)/dist/libnetwork-plugin:/libnetwork-plugin -ti docker:$(DOCKER_VERSION) --cluster-store=etcd://$(LOCAL_IP_ENV):2379
	docker exec -tid --privileged dind /libnetwork-plugin
	# To speak to this docker:
	# export DOCKER_HOST=localhost:5375

.PHONY: test
# Run the unit tests.
test:
	CGO_ENABLED=0 ginkgo -v

test-containerized: run-plugin
	docker cp dind:/usr/local/bin/docker .
	docker run -ti --rm --net=host \
		-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v $(CURDIR)/docker:/usr/bin/docker	\
		-e EXTRA_GROUP_ID=`getent group docker | cut -d: -f3` \
		-e LOCAL_USER_ID=`id -u $$USER` \
		calico/go-build sh -c '\
			cd  /go/src/github.com/projectcalico/libnetwork-plugin && \
			make test'

