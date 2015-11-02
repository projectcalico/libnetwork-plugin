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
import logging
from tests.st.utils.utils import assert_number_endpoints, assert_profile, \
    get_profile_name

logger = logging.getLogger(__name__)


class TestMainline(TestBase):
    def test_mainline(self):
        """
        Setup two endpoints on one host and check connectivity then teardown.
        """
        # TODO - add in IPv6 as part of this flow.
        with DockerHost('host') as host:
            # Set up two endpoints on one host
            network = host.create_network("testnet")
            workload1 = host.create_workload(str(uuid.uuid4()), network=network)
            workload2 = host.create_workload(str(uuid.uuid4()), network=network)

            # Assert that endpoints are in Calico
            assert_number_endpoints(host, 2)

            # Assert that the profile has been created for the network
            profile_name = get_profile_name(host, network)
            assert_profile(host, profile_name)

            # Allow network to converge
            # Check connectivity.
            workload1.assert_can_ping(workload2.ip, retries=5)
            self.assert_connectivity([workload1, workload2])

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
