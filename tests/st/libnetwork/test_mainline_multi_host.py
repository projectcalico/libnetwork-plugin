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
from tests.st.utils.utils import get_ip, assert_network, assert_profile, \
    assert_number_endpoints, get_profile_name


class MultiHostMainline(TestBase):

    def test_multi_host(self):
        """
        Run a mainline multi-host test.

        Because multihost tests are slow to setup, this tests most mainline
        functionality in a single test.

        - Create two hosts
        - Create two networks, both using Calico for IPAM and networking.
        - Create a workload on each host in each network.
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
            run_plugin_command = 'docker run -d ' \
                                 '--net=host --privileged ' + \
                                 '-e CALICO_ETCD_AUTHORITY=%s:2379 ' \
                                 '-v /run/docker/plugins:/run/docker/plugins ' \
                                 '-v /var/run/docker.sock:/var/run/docker.sock ' \
                                 '-v /lib/modules:/lib/modules ' \
                                 '--name libnetwork-plugin ' \
                                 'calico/libnetwork-plugin' % (get_ip(),)

            host1.start_calico_node()
            host1.execute(run_plugin_command)

            host2.start_calico_node()
            host2.execute(run_plugin_command)

            # Create the networks on host1, but it should be usable from all
            # hosts.  We create one network using the default driver, and the
            # other using the Calico driver.
            testnet1 = host1.create_network("testnet1", ipam_driver="calico-ipam", driver="calico")
            testnet2 = host1.create_network("testnet2", ipam_driver="calico-ipam", driver="calico")

            # Assert that the networks can be seen on host2
            assert_network(host2, testnet1)
            assert_network(host2, testnet2)

            # Create two workloads on host1 - one in each network
            workload_h1n1 = host1.create_workload("workload_h1n1",
                                                    network=testnet1)
            workload_h1n2 = host1.create_workload("workload_h1n2",
                                                    network=testnet2)

            # Profiles aren't created until a workloads are created.
            # Assert that the profiles have been created for the networks
            assert_profile(host1, "testnet1")

            # Create similar workloads in network 2.
            workload_h2n1 = host2.create_workload("workload_h2n1",
                                                    network=testnet1)
            workload_h2n2 = host2.create_workload("workload_h2n2",
                                                    network=testnet2)
            assert_profile(host1, "testnet2")

            # Assert that endpoints are in Calico
            assert_number_endpoints(host1, 2)
            assert_number_endpoints(host2, 2)

            # Assert that workloads can communicate with each other on network
            # 1, and not those on network 2.  Ping using IP for all workloads,
            # and by hostname for workloads on the same network (note that
            # a workloads own hostname does not work).
            self.assert_connectivity(retries=5,
                                     pass_list=[workload_h1n1,
                                                workload_h2n1],
                                     fail_list=[workload_h1n2,
                                                workload_h2n2])

            workload_h1n1.execute("ping -c 1 -W 5 workload_h2n1")
            workload_h2n1.execute("ping -c 1 -W 5 workload_h1n1")

            # Test deleting the network. It will fail if there are any
            # endpoints connected still.
            self.assertRaises(CommandExecError, testnet1.delete)
            self.assertRaises(CommandExecError, testnet2.delete)

            # For network 1, disconnect (or "detach" or "leave") the endpoints
            # Assert that an endpoint is removed from calico and can't ping
            testnet1.disconnect(host1, workload_h1n1)
            assert_number_endpoints(host1, 1)
            testnet1.disconnect(host2, workload_h2n1)
            assert_number_endpoints(host2, 1)

            workload_h1n1.assert_cant_ping(workload_h2n1.ip, retries=5)

            # Repeat for network 2.  All endpoints should be removed.
            testnet2.disconnect(host1, workload_h1n2)
            assert_number_endpoints(host1, 0)
            testnet2.disconnect(host2, workload_h2n2)
            assert_number_endpoints(host2, 0)
            workload_h1n2.assert_cant_ping(workload_h2n2.ip, retries=5)

            # Remove the workloads, so the endpoints can be unpublished, then
            # the delete should succeed.
            host1.remove_workloads()
            host2.remove_workloads()

            # Remove the network
            testnet1.delete()
            testnet2.delete()

