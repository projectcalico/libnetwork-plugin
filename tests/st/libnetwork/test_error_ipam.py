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
from tests.st.utils.utils import get_ip, assert_number_endpoints, assert_profile, \
    get_profile_name, ETCD_CA, ETCD_CERT, ETCD_KEY, ETCD_HOSTNAME_SSL, \
    ETCD_SCHEME

logger = logging.getLogger(__name__)


ADDITIONAL_DOCKER_OPTIONS = "--cluster-store=etcd://%s:2379 " % \
                                utils.get_ip()

class TestErrors(TestBase):
    def test_no_ipam(self):
        """
        Try creating a network and using calico for networking but not IPAM. CHeck that it fails.
        """
        with DockerHost('host',
                        additional_docker_options=ADDITIONAL_DOCKER_OPTIONS,
                        post_docker_commands=["docker load -i /code/calico-node-libnetwork.tar"],
                        start_calico=False) as host:

            run_plugin_command = 'docker run -d ' \
                                 '--net=host --privileged ' + \
                                 '-e CALICO_ETCD_AUTHORITY=%s:2379 ' \
                                 '-v /run/docker/plugins:/run/docker/plugins ' \
                                 '-v /var/run/docker.sock:/var/run/docker.sock ' \
                                 '-v /lib/modules:/lib/modules ' \
                                 '--name libnetwork-plugin ' \
                                 'calico/libnetwork-plugin' % (get_ip(),)

            host.execute(run_plugin_command)

            # Create network using calico for network driver ONLY
            try:
                network = host.create_network("shouldfailnet", driver="calico")
            except Exception, e:
                self.assertIn("Non-Calico IPAM driver is used", str(e))
