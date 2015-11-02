.PHONEY: all binary test ut ut-circle st clean setup-env run-etcd install-completion fast-st

SRCDIR=libnetwork
SRC_FILES=$(wildcard $(SRCDIR)/*.py)
BUILD_DIR=build_calicoctl
BUILD_FILES=$(BUILD_DIR)/Dockerfile $(BUILD_DIR)/requirements.txt
NODE_FILES=Dockerfile start.sh

# These variables can be overridden by setting an environment variable.
LOCAL_IP_ENV?=$(shell ip route get 8.8.8.8 | head -1 | cut -d' ' -f8)
ST_TO_RUN?=tests/st/

default: all
all: test
node: caliconode.created

caliconode.created: $(SRC_FILES) $(NODE_FILES)
	docker build -t calico/node-libnetwork .
	touch caliconode.created

calicobuild.created: $(BUILD_FILES)
	cd build_calicoctl; docker build -t calico/build-libnetwork .
	touch calicobuild.created

dist/calicoctl:
	mkdir dist
	curl -L http://www.projectcalico.org/latest/calicoctl -o dist/calicoctl
	chmod +x dist/calicoctl

test: st ut

ut: calicobuild.created
	# Use the `root` user, since code coverage requires the /code directory to
	# be writable.  It may not be writable for the `user` account inside the
	# container.
	docker run --rm -v `pwd`:/code -u root \
	calico/build-libnetwork bash -c \
	'/tmp/etcd -data-dir=/tmp/default.etcd/ >/dev/null 2>&1 & \
	nosetests tests/unit  -c nose.cfg'

# TODO
ut-circle: calicobuild.created
	# Can't use --rm on circle
	# Circle also requires extra options for reporting.
	docker run \
	-v `pwd`:/code \
	-v $(CIRCLE_TEST_REPORTS):/circle_output \
	-e COVERALLS_REPO_TOKEN=$(COVERALLS_REPO_TOKEN) \
	calico/build-libnetwork bash -c \
	'/tmp/etcd -data-dir=/tmp/default.etcd/ >/dev/null 2>&1 & \
	nosetests tests/unit -c nose.cfg \
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

st: docker dist/calicoctl busybox.tgz calico-node.tgz calico-node-libnetwork.tgz run-etcd
	nosetests $(ST_TO_RUN) -sv --nologcapture --with-timer

run-plugin: node
	docker run -ti --privileged --net=host -v /run/docker/plugins:/run/docker/plugins -e ETCD_AUTHORITY=$(LOCAL_IP_ENV):2379 calico/node-libnetwork

run-plugin-local:
	sudo gunicorn --reload -b unix:///run/docker/plugins/calico.sock libnetwork.driver_plugin:app

run-etcd:
	@-docker rm -f calico-etcd
	docker run --detach \
	--net=host \
	--name calico-etcd quay.io/coreos/etcd:v2.0.11 \
	--advertise-client-urls "http://$(LOCAL_IP_ENV):2379,http://127.0.0.1:2379" \
	--listen-client-urls "http://0.0.0.0:2379"

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

docker:
	# Download the latest docker to test.
	curl https://get.docker.com/builds/Linux/x86_64/docker-1.9.0 -o docker
	chmod +x docker

semaphore:
	# Install deps
	pip install sh nose-timer nose netaddr git+https://github.com/projectcalico/libcalico.git

	# Upgrade Docker
	stop docker
	curl https://get.docker.com/builds/Linux/x86_64/docker-1.9.0 -o /usr/bin/docker
	cp /usr/bin/docker .
	start docker

	# Ensure Semaphore has loaded the required modules
	modprobe -a ip6_tables xt_set

	# Run the STs
	make st

clean:
	-rm -f docker
	-rm -f *.created
	-rm -rf dist
	-rm -f *.tgz
	-docker run -v /var/run/docker.sock:/var/run/docker.sock -v /var/lib/docker:/var/lib/docker --rm martin/docker-cleanup-volumes
