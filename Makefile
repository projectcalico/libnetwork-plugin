SRC_FILES=$(shell find . -type f -name '*.go')

# These variables can be overridden by setting an environment variable.
LOCAL_IP_ENV?=$(shell ip route get 8.8.8.8 | head -1 | cut -d' ' -f8)
ST_TO_RUN?=tests/st
# Can exclude the slower tests with "-a '!slow'"
ST_OPTIONS?=
HOST_CHECKOUT_DIR?=$(shell pwd)

default: all
all: test
test: st

calico/libnetwork-plugin: libnetwork-plugin.created

# Use this to populate the vendor directory after checking out the repository.
# To update upstream dependencies, delete the glide.lock file first.
vendor: glide.yaml
	# To build without Docker just run "glide install -strip-vendor"
	docker run --rm -v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin:rw \
      --entrypoint /bin/sh dockerepo/glide -e -c ' \
		cd /go/src/github.com/projectcalico/libnetwork-plugin && \
		glide install -strip-vendor && \
		chown $(shell id -u):$(shell id -u) -R vendor'

install:
	CGO_ENABLED=0 go install github.com/projectcalico/libnetwork-plugin

# Run the build in a container. Useful for CI
.PHONY: build-containerized
build-containerized: vendor
	mkdir -p dist
	docker run --rm \
	-v $(CURDIR):/go/src/github.com/projectcalico/libnetwork-plugin:ro \
	-v $(CURDIR)/dist:/go/src/github.com/projectcalico/libnetwork-plugin/dist \
	golang:1.7 sh -c '\
		cd  /go/src/github.com/projectcalico/libnetwork-plugin && \
		make build && \
		chown -R $(shell id -u):$(shell id -u) dist'


build: $(SRC_FILES) vendor
	CGO_ENABLED=0 go build -v -o dist/libnetwork-plugin -ldflags "-X main.VERSION=$(shell git describe --tags --dirty) -s -w" main.go

libnetwork-plugin.created: Dockerfile build-containerized
	docker build -t calico/libnetwork-plugin .
	touch libnetwork-plugin.created

dist/calicoctl:
	mkdir dist
	curl -L http://www.projectcalico.org/builds/calicoctl -o dist/calicoctl
	chmod +x dist/calicoctl

busybox.tar:
	docker pull busybox:latest
	docker save busybox:latest -o busybox.tar

calico-node.tar:
	docker pull calico/node:latest
	docker save calico/node:latest -o calico-node.tar

calico-node-libnetwork.tar: libnetwork-plugin.created
	docker save calico/libnetwork-plugin:latest -o calico-node-libnetwork.tar

# Install or update the tools used by the build
.PHONY: update-tools
update-tools:
	go get -u github.com/Masterminds/glide
	go get -u github.com/kisielk/errcheck
	go get -u golang.org/x/tools/cmd/goimports
	go get -u github.com/golang/lint/golint
	go get -u github.com/onsi/ginkgo/ginkgo

# Perform static checks on the code. The golint checks are allowed to fail, the others must pass.
.PHONY: static-checks
static-checks: vendor
	# Format the code and clean up imports
	find -name '*.go'  -not -path "./vendor/*" |xargs goimports -w

	# Check for coding mistake and missing error handling
	go vet -x $(glide nv)
	errcheck . ./datastore/... ./utils/... ./driver/...

	# Check code style
	-golint main.go
	-golint datastore
	-golint utils
	-golint driver

st:  dist/calicoctl busybox.tar calico-node.tar calico-node-libnetwork.tar run-etcd
	# Use the host, PID and network namespaces from the host.
	# Privileged is needed since 'calico node' write to /proc (to enable ip_forwarding)
	# Map the docker socket in so docker can be used from inside the container
	# HOST_CHECKOUT_DIR is used for volume mounts on containers started by this one.
	# All of code under test is mounted into the container.
	#   - This also provides access to calicoctl and the docker client
	docker run --uts=host \
	           --pid=host \
	           --net=host \
	           --privileged \
	           -e HOST_CHECKOUT_DIR=$(HOST_CHECKOUT_DIR) \
	           -e DEBUG_FAILURES=$(DEBUG_FAILURES) \
	           --rm -ti \
	           -v /var/run/docker.sock:/var/run/docker.sock \
	           -v $(CURDIR):/code \
	           calico/test \
	           sh -c 'cp -ra tests/st/libnetwork/ /tests/st && cd / && nosetests $(ST_TO_RUN) -sv --nologcapture --with-timer $(ST_OPTIONS)'

run-plugin: libnetwork-plugin.created
	docker run --rm --net=host --privileged -e CALICO_ETCD_AUTHORITY=$(LOCAL_IP_ENV):2379 -v /run/docker/plugins:/run/docker/plugins -v /var/run/docker.sock:/var/run/docker.sock -v /lib/modules:/lib/modules --name calico-node-libnetwork calico/libnetwork-plugin /libnetwork-plugin


run-etcd:
	@-docker rm -f calico-etcd calico-etcd-ssl
	docker run --detach \
	--net=host \
	--name calico-etcd quay.io/coreos/etcd:v2.0.11 \
	--advertise-client-urls "http://$(LOCAL_IP_ENV):2379,http://127.0.0.1:2379" \
	--listen-client-urls "http://0.0.0.0:2379"

semaphore:
	docker version

	# Ensure Semaphore has loaded the required modules
	modprobe -a ip6_tables xt_set

	# Run the STs
	make st

clean:
	-rm -f *.created
	-rm -rf dist
	-rm -f *.tar
	-rm -rf vendor
	-docker run -v /var/run/docker.sock:/var/run/docker.sock -v /var/lib/docker:/var/lib/docker --rm martin/docker-cleanup-volumes
