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
from tests.st.utils.docker_host import DockerHost
from tests.st.utils.exceptions import CommandExecError


class MultiHostMainline(TestBase):

    def test_multi_host(self):
        """
        Run a mainline multi-host test.

        Because multihost tests are slow to setup, this tests most mainline
        functionality in a single test.

        Create two hosts, a single network, one workload on each host and
        ping between them.
        """
        with DockerHost('host1') as host1, DockerHost('host2') as host2:
            # TODO work IPv6 into this test too

            # Create the network on host1, but it should be usable from all
            # hosts.
            network = host1.create_network(str(uuid.uuid4()))
            # TODO Assert that the network can be seen on host2

            workload_host1 = host1.create_workload("workload1",
                                                   network=network)
            workload_host2 = host2.create_workload("workload2",
                                                   network=network)

            # TODO - assert on output of endpoint show and endpoint profile
            # show commands.
            workload_host1.assert_can_ping(workload_host2.ip, retries=5)

            # Ping using IP addresses
            self.assert_connectivity(pass_list=[workload_host1,
                                                workload_host2])
            # Ping using container names
            workload_host1.execute("ping -c 1 -W 1 workload2")
            workload_host2.execute("ping -c 1 -W 1 workload1")

            # TODO - detach ("leave") the endpoints - (assert can't ping and
            #  endpoints are removed from calicoctl)

            # Test deleting the network. It will fail if there are any
            # endpoints connected still.
            self.assertRaises(CommandExecError, network.delete)

            # Remove the workloads, so the endpoints can be unpublished, then
            # the delete should succeed.
            host1.remove_workloads()
            host2.remove_workloads()

            # TODO - remove the network - (assert profile is removed)
            network.delete()

            # TODO - Remove this calico node

            # TODO Would like to assert that there are no errors in the logs...
