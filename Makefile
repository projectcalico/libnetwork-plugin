.PHONEY: all binary test ut ut-circle st st-ssl clean setup-env run-etcd run-etcd-ssl install-completion

SRCDIR=libnetwork
SRC_FILES=$(wildcard $(SRCDIR)/*.py)
BUILD_DIR=build_calicoctl
BUILD_FILES=$(BUILD_DIR)/Dockerfile $(BUILD_DIR)/requirements.txt
NODE_FILES=Dockerfile start.sh

# These variables can be overridden by setting an environment variable.
LOCAL_IP_ENV?=$(shell ip route get 8.8.8.8 | head -1 | cut -d' ' -f8)
ST_TO_RUN?=tests/st
# Can exclude the slower tests with "-a '!slow'"
ST_OPTIONS?=
HOST_CHECKOUT_DIR?=$(shell pwd)

default: all
all: test
node: caliconode.created

caliconode.created: $(SRC_FILES) $(NODE_FILES)
	docker build -t calico/node-libnetwork .
	touch caliconode.created

dist/calicoctl:
	mkdir dist
	curl -L http://www.projectcalico.org/builds/calicoctl -o dist/calicoctl
	chmod +x dist/calicoctl

test: st ut
ssl-certs: certs/.certificates.created ## Generate self-signed SSL certificates

ut: 
	docker run --rm -v `pwd`:/code calico/test nosetests tests/unit  -c nose.cfg

ut-circle:
	# Can't use --rm on circle
	# Circle also requires extra options for reporting.
	docker run \
	-v `pwd`:/code \
	-v $(CIRCLE_TEST_REPORTS):/circle_output \
	-e COVERALLS_REPO_TOKEN=$(COVERALLS_REPO_TOKEN) \
	calico/test sh -c \
	'nosetests tests/unit -c nose.cfg \
	--with-xunit --xunit-file=/circle_output/output.xml; RC=$$?;\
	[[ ! -z "$$COVERALLS_REPO_TOKEN" ]] && coveralls || true; exit $$RC'

busybox.tgz:
	docker pull busybox:latest
	docker save busybox:latest | gzip -c > busybox.tgz

calico-node.tgz:
	docker pull calico/node:latest
	docker save calico/node:latest | gzip -c > calico-node.tgz

calico-node-libnetwork.tgz: caliconode.created
	docker save calico/node-libnetwork:latest | gzip -c > calico-node-libnetwork.tgz

## Generate the keys and certificates for running etcd with SSL.
certs/.certificates.created:
	mkdir -p certs
	curl -L "https://github.com/projectcalico/cfssl/releases/download/1.2.1/cfssl" -o certs/cfssl
	curl -L "https://github.com/projectcalico/cfssl/releases/download/1.2.1/cfssljson" -o certs/cfssljson
	chmod a+x certs/cfssl
	chmod a+x certs/cfssljson

	certs/cfssl gencert -initca tests/st/ssl-config/ca-csr.json | certs/cfssljson -bare certs/ca
	certs/cfssl gencert \
	  -ca certs/ca.pem \
	  -ca-key certs/ca-key.pem \
	  -config tests/st/ssl-config/ca-config.json \
	  tests/st/ssl-config/req-csr.json | certs/cfssljson -bare certs/client
	certs/cfssl gencert \
	  -ca certs/ca.pem \
	  -ca-key certs/ca-key.pem \
	  -config tests/st/ssl-config/ca-config.json \
	  tests/st/ssl-config/req-csr.json | certs/cfssljson -bare certs/server

	touch certs/.certificates.created

st:  dist/calicoctl busybox.tgz calico-node.tgz calico-node-libnetwork.tgz run-etcd
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
	           -v `pwd`:/code \
	           calico/test \
	           sh -c 'cp -ra tests/st/libnetwork/ /tests/st && cd / && nosetests $(ST_TO_RUN) -sv --nologcapture --with-timer $(ST_OPTIONS)'

## Run the STs in a container using etcd with SSL certificate/key/CA verification.
st-ssl: dist/calicoctl busybox.tgz calico-node.tgz calico-node-libnetwork.tgz run-etcd-ssl
	# Use the host, PID and network namespaces from the host.
        # Privileged is needed since 'calico node' write to /proc (to enable ip_forwarding)
        # Map the docker socket in so docker can be used from inside the container
        # HOST_CHECKOUT_DIR is used for volume mounts on containers started by this one.
        # All of code under test is mounted into the container.
        #   - This also provides access to calicoctl and the docker client
        # Mount the full path to the etcd certs directory.
        #   - docker copies this directory directly from the host, but the
        #     calicoctl node command reads the files from the test container
	docker run --uts=host \
	           --pid=host \
	           --net=host \
	           --privileged \
	           -e HOST_CHECKOUT_DIR=$(HOST_CHECKOUT_DIR) \
	           -e ETCD_SCHEME=https \
	           -e ETCD_CA_CERT_FILE=`pwd`/certs/ca.pem \
	           -e ETCD_CERT_FILE=`pwd`/certs/client.pem \
	           -e ETCD_KEY_FILE=`pwd`/certs/client-key.pem \
	           -e DEBUG_FAILURES=$(DEBUG_FAILURES) \
	           --rm -ti \
	           -v /var/run/docker.sock:/var/run/docker.sock \
	           -v `pwd`:/code \
	           -v `pwd`/certs:`pwd`/certs \
	           calico/test \
	           sh -c 'cp -ra tests/st/* /tests/st && cd / && nosetests $(ST_TO_RUN) -sv --nologcapture --with-timer $(ST_OPTIONS)'

run-plugin: node
	docker run -ti --privileged --net=host -v /run/docker/plugins:/run/docker/plugins -e ETCD_AUTHORITY=$(LOCAL_IP_ENV):2379 calico/node-libnetwork

run-plugin-local:
	sudo gunicorn --reload -b unix:///run/docker/plugins/calico.sock libnetwork.driver_plugin:app

run-etcd:
	@-docker rm -f calico-etcd calico-etcd-ssl
	docker run --detach \
	--net=host \
	--name calico-etcd quay.io/coreos/etcd:v2.0.11 \
	--advertise-client-urls "http://$(LOCAL_IP_ENV):2379,http://127.0.0.1:2379" \
	--listen-client-urls "http://0.0.0.0:2379"

## Run etcd in a container with SSL verification. Used primarily by STs.
run-etcd-ssl: certs/.certificates.created add-ssl-hostname
	@-docker rm -f calico-etcd calico-etcd-ssl
	docker run --detach \
	--net=host \
	-v `pwd`/certs:/etc/calico/certs \
	--name calico-etcd-ssl quay.io/coreos/etcd:v2.0.11 \
	--cert-file "/etc/calico/certs/server.pem" \
	--key-file "/etc/calico/certs/server-key.pem" \
	--ca-file "/etc/calico/certs/ca.pem" \
	--advertise-client-urls "https://etcd-authority-ssl:2379,https://localhost:2379" \
	--listen-client-urls "https://0.0.0.0:2379"

add-ssl-hostname:
	# Set "LOCAL_IP etcd-authority-ssl" in /etc/hosts to use as a hostname for etcd with ssl
	if ! grep -q "etcd-authority-ssl" /etc/hosts; then \
	  echo "\n# Host used by Calico's ETCD with SSL\n$(LOCAL_IP_ENV) etcd-authority-ssl" >> /etc/hosts; \
	fi


create-dind:
	@echo "You may want to load calico-node with"
	@echo "docker load --input /code/calico-node.tgz"
	@ID=$$(docker run --privileged -v `pwd`:/code -v `pwd`/docker:/usr/local/bin/docker \
	-tid calico/dind:latest --cluster-store=etcd://$(LOCAL_IP_ENV):2379) ;\
	docker exec -ti $$ID sh;\
	docker rm -f $$ID

demo-environment: docker dist/calicoctl busybox.tgz calico-node.tgz calico-node-libnetwork.tgz run-etcd
	-docker rm -f host1 host2
	docker run --name host1 -e ETCD_AUTHORITY=$(LOCAL_IP_ENV):2379 --privileged \
	-v `pwd`:/code -v `pwd`/docker:/usr/local/bin/docker \
	-tid calico/dind:libnetwork --cluster-store=etcd://$(LOCAL_IP_ENV):2379 ;\
	docker run --name host2 -e ETCD_AUTHORITY=$(LOCAL_IP_ENV):2379 --privileged \
	-v `pwd`:/code -v `pwd`/docker:/usr/local/bin/docker \
	-tid calico/dind:libnetwork --cluster-store=etcd://$(LOCAL_IP_ENV):2379 ;\
	docker exec -it host1 sh -c 'docker load -i /code/calico-node.tgz'
	docker exec -it host1 sh -c 'docker load -i /code/busybox.tgz'
	docker exec -it host1 sh -c 'docker load -i /code/calico-node-libnetwork.tgz'
	docker exec -it host2 sh -c 'docker load -i /code/calico-node.tgz'
	docker exec -it host2 sh -c 'docker load -i /code/busybox.tgz'
	docker exec -it host2 sh -c 'docker load -i /code/calico-node-libnetwork.tgz'

	@echo "Two dind hosts (host1, host2) are now ready."
	@echo "Connect using:"
	@echo "docker exec -ti host1 sh"

semaphore:
	# Use the downloaded docker locally, not just with Docker in Docker STs
	docker version

	# Ensure Semaphore has loaded the required modules
	modprobe -a ip6_tables xt_set

	# Run the STs
	make st

	# Run subset of STs with secure etcd (only a few total, so just run all of them)
	# Temporarily disable the secure STs
	make st-ssl

clean:
	-rm -f *.created
	-rm -rf dist
	-rm -rf certs
	-rm -f *.tgz
	-docker run -v /var/run/docker.sock:/var/run/docker.sock -v /var/lib/docker:/var/lib/docker --rm martin/docker-cleanup-volumes
