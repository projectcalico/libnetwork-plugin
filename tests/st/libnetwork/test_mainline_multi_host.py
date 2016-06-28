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
from tests.st.libnetwork.test_mainline_single_host import \
    ADDITIONAL_DOCKER_OPTIONS, POST_DOCKER_COMMANDS

from tests.st.test_base import TestBase
from tests.st.utils.docker_host import DockerHost
from tests.st.utils.exceptions import CommandExecError
from tests.st.utils.utils import assert_network, assert_profile, \
    assert_number_endpoints, get_profile_name


class MultiHostMainline(TestBase):

    def test_multi_host(self):
        """
        Run a mainline multi-host test.

        Because multihost tests are slow to setup, this tests most mainline
        functionality in a single test.

        - Create two hosts
        - Create a network using the default IPAM driver, and a workload on
          each host assigned to that network.
        - Create a network using the Calico IPAM driver, and a workload on
          each host assigned to that network.
        - Check that hosts on the same network can ping each other.
        - Check that hosts on different networks cannot ping each other.
        """
        with DockerHost('host1',
                        additional_docker_options=ADDITIONAL_DOCKER_OPTIONS,
                        post_docker_commands=POST_DOCKER_COMMANDS,
                        start_calico=False) as host1, \
            DockerHost('host2',
                       additional_docker_options=ADDITIONAL_DOCKER_OPTIONS,
                       post_docker_commands=POST_DOCKER_COMMANDS,
                       start_calico=False) as host2:
            # TODO work IPv6 into this test too
            host1.start_calico_node("--libnetwork")
            host2.start_calico_node("--libnetwork")

            # Create the networks on host1, but it should be usable from all
            # hosts.  We create one network using the default driver, and the
            # other using the Calico driver.
            network1 = host1.create_network("testnet1", ipam_driver="default")
            network2 = host1.create_network("testnet2", ipam_driver="calico")

            # Assert that the networks can be seen on host2
            assert_network(host2, network2)
            assert_network(host2, network1)

            # Assert that the profiles have been created for the networks
            profile_name1 = get_profile_name(host1, network1)
            assert_profile(host1, profile_name1)
            profile_name2 = get_profile_name(host1, network2)
            assert_profile(host1, profile_name2)

            # Create two workloads on host1 and one on host2 all in network 1.
            workload_h1n2_1 = host1.create_workload("workload_h1n2_1",
                                                    network=network2)
            workload_h1n2_2 = host1.create_workload("workload_h1n2_2",
                                                    network=network2)
            workload_h2n2_1 = host2.create_workload("workload_h2n2_1",
                                                    network=network2)

            # Create similar workloads in network 2.
            workload_h2n1_1 = host2.create_workload("workload_h2n1_1",
                                                    network=network1)
            workload_h1n1_1 = host1.create_workload("workload_h1n1_1",
                                                    network=network1)
            workload_h1n1_2 = host1.create_workload("workload_h1n1_2",
                                                    network=network1)

            # Assert that endpoints are in Calico
            assert_number_endpoints(host1, 4)
            assert_number_endpoints(host2, 2)

            # Assert that workloads can communicate with each other on network
            # 1, and not those on network 2.  Ping using IP for all workloads,
            # and by hostname for workloads on the same network (note that
            # a workloads own hostname does not work).
            self.assert_connectivity(retries=2,
                                     pass_list=[workload_h1n1_1,
                                                workload_h1n1_2,
                                                workload_h2n1_1])
            # TODO: docker_gwbridge iptable FORWARD rule takes precedence over
            # Felix, resulting in temporary lack of isolation between a
            # container on the bridge communicating with a non-bridge container
            # on the same host.  Therefore we cannot yet test isolation.
            #                          fail_list=[workload_h1n2_1,
            #                                     workload_h1n2_2,
            #                                     workload_h2n2_1])
            workload_h1n1_1.execute("ping -c 1 -W 1 workload_h1n1_2")
            workload_h1n1_1.execute("ping -c 1 -W 1 workload_h2n1_1")

            # Repeat with network 2.
            self.assert_connectivity(pass_list=[workload_h1n2_1,
                                                workload_h1n2_2,
                                                workload_h2n2_1])
            # TODO - see comment above
            #                         fail_list=[workload_h1n1_1,
            #                                    workload_h1n1_2,
            #                                    workload_h1n1_1])
            workload_h1n2_1.execute("ping -c 1 -W 1 workload_h1n2_2")
            workload_h1n2_1.execute("ping -c 1 -W 1 workload_h2n2_1")

            # Test deleting the network. It will fail if there are any
            # endpoints connected still.
            self.assertRaises(CommandExecError, network1.delete)
            self.assertRaises(CommandExecError, network2.delete)

            # For network 1, disconnect (or "detach" or "leave") the endpoints
            # Assert that an endpoint is removed from calico and can't ping
            network1.disconnect(host1, workload_h1n1_1)
            network1.disconnect(host1, workload_h1n1_2)
            assert_number_endpoints(host1, 2)
            network1.disconnect(host2, workload_h2n1_1)
            assert_number_endpoints(host2, 1)
            workload_h1n1_1.assert_cant_ping(workload_h2n2_1.ip, retries=5)

            # Repeat for network 2.  All endpoints should be removed.
            network2.disconnect(host1, workload_h1n2_1)
            network2.disconnect(host1, workload_h1n2_2)
            assert_number_endpoints(host1, 0)
            network2.disconnect(host2, workload_h2n2_1)
            assert_number_endpoints(host2, 0)
            workload_h1n1_1.assert_cant_ping(workload_h2n2_1.ip, retries=5)

            # Remove the workloads, so the endpoints can be unpublished, then
            # the delete should succeed.
            host1.remove_workloads()
            host2.remove_workloads()

            # Remove the network and assert profile is removed
            network1.delete()
            network2.delete()
            self.assertRaises(AssertionError, assert_profile, host1,
                              profile_name1)

            # TODO - Remove this calico node

            # TODO Would like to assert that there are no errors in the logs...

