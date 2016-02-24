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
import logging

from tests.st.test_base import TestBase
from tests.st.utils.docker_host import DockerHost
from tests.st.utils.utils import assert_number_endpoints
from tests.st.libnetwork.test_mainline_single_host import \
    ADDITIONAL_DOCKER_OPTIONS, POST_DOCKER_COMMANDS

logger = logging.getLogger(__name__)


class TestAssignIP(TestBase):
    def test_assign_specific_ip(self):
        """
        Test that a libnetwork assigned IP is allocated to the container with
        Calico when using the '--ip' flag on docker run.
        """
        with DockerHost('host1',
                        additional_docker_options=ADDITIONAL_DOCKER_OPTIONS,
                        post_docker_commands=POST_DOCKER_COMMANDS,
                        start_calico=False) as host1, \
            DockerHost('host2',
                       additional_docker_options=ADDITIONAL_DOCKER_OPTIONS,
                       post_docker_commands=POST_DOCKER_COMMANDS,
                       start_calico=False) as host2:

            host1.start_calico_node("--libnetwork")
            host2.start_calico_node("--libnetwork")

            # Set up one endpoints on each host
            workload1_ip = "192.168.1.101"
            workload2_ip = "192.168.1.102"
            subnet = "192.168.0.0/16"
            network = host1.create_network("testnet", subnet=subnet)
            workload1 = host1.create_workload("workload1",
                                              network=network,
                                              ip=workload1_ip)
            workload2 = host2.create_workload("workload2",
                                              network=network,
                                              ip=workload2_ip)

            self.assertEquals(workload1_ip, workload1.ip)
            self.assertEquals(workload2_ip, workload2.ip)

            # Allow network to converge
            # Check connectivity with assigned IPs
            workload1.assert_can_ping(workload2_ip, retries=5)
            workload2.assert_can_ping(workload1_ip, retries=5)

            # Disconnect endpoints from the network
            # Assert can't ping and endpoints are removed from Calico
            network.disconnect(host1, workload1)
            network.disconnect(host2, workload2)
            workload1.assert_cant_ping(workload2_ip, retries=5)
            assert_number_endpoints(host1, 0)
            assert_number_endpoints(host2, 0)
            network.delete()
