# Copyright 2015 Metaswitch Networks
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import uuid

from tests.st.test_base import TestBase
from tests.st.utils import utils
from tests.st.utils.docker_host import DockerHost
import logging
from tests.st.utils.utils import assert_number_endpoints, assert_profile, \
    get_profile_name, ETCD_CA, ETCD_CERT, ETCD_KEY, ETCD_HOSTNAME_SSL, \
    ETCD_SCHEME

logger = logging.getLogger(__name__)

POST_DOCKER_COMMANDS = ["docker load -i /code/calico-node.tgz",
                        "docker load -i /code/busybox.tgz",
                        "docker load -i /code/calico-node-libnetwork.tgz"]

if ETCD_SCHEME == "https":
    ADDITIONAL_DOCKER_OPTIONS = "--cluster-store=etcd://%s:2379 " \
                                "--cluster-store-opt kv.cacertfile=%s " \
                                "--cluster-store-opt kv.certfile=%s " \
                                "--cluster-store-opt kv.keyfile=%s " % \
                                (ETCD_HOSTNAME_SSL, ETCD_CA, ETCD_CERT,
                                 ETCD_KEY)
else:
    ADDITIONAL_DOCKER_OPTIONS = "--cluster-store=etcd://%s:2379 " % \
                                utils.get_ip()

class TestMainline(TestBase):
    def test_mainline(self):
        """
        Setup two endpoints on one host and check connectivity then teardown.
        """
        # TODO - add in IPv6 as part of this flow.
        with DockerHost('host',
                        additional_docker_options=ADDITIONAL_DOCKER_OPTIONS,
                        post_docker_commands=POST_DOCKER_COMMANDS,
                        start_calico=False) as host:
            host.start_calico_node("--libnetwork")

            # Set up two endpoints on one host
            network = host.create_network("testnet")
            workload1 = host.create_workload("workload1", network=network)
            workload2 = host.create_workload("workload2", network=network)

            # Assert that endpoints are in Calico
            assert_number_endpoints(host, 2)

            # Assert that the profile has been created for the network
            profile_name = get_profile_name(host, network)
            assert_profile(host, profile_name)

            # Allow network to converge
            # Check connectivity.
            workload1.assert_can_ping("workload2", retries=5)
            workload2.assert_can_ping("workload1", retries=5)

            # Inspect the workload to ensure the MAC address is set
            # correctly.
            format = "'{{.NetworkSettings.Networks.%s.MacAddress}}'" % network
            mac = host.execute("docker inspect --format %s %s" % (format,
                                                                  workload1.name))
            self.assertEquals(mac.lower(), "ee:ee:ee:ee:ee:ee")

            # Disconnect endpoints from the network
            # Assert can't ping and endpoints are removed from Calico
            network.disconnect(host, workload1)
            network.disconnect(host, workload2)
            workload1.assert_cant_ping(workload2.ip, retries=5)
            assert_number_endpoints(host, 0)

            # Remove the endpoints on the host
            # TODO (assert IPs are released)
            host.remove_workloads()

            # Remove the network and assert profile is removed
            network.delete()
            self.assertRaises(AssertionError, assert_profile, host, profile_name)

            # TODO - Remove this calico node
