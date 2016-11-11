# Copyright 2015 Tigera, Inc. All rights reserved.
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

from subprocess import check_output

from tests.st.test_base import TestBase
from tests.st.utils.docker_host import DockerHost
from tests.st.utils.utils import get_ip
from tests.st.libnetwork.test_mainline_single_host import \
    ADDITIONAL_DOCKER_OPTIONS

logger = logging.getLogger(__name__)


class TestOptError(TestBase):
    def test_error_arbitrary_opts(self):
        """
        Test that a NetworkDriver.CreateNetwork fails when there are any '--opt' options passed.
        """
        with DockerHost('host',
                        additional_docker_options=ADDITIONAL_DOCKER_OPTIONS,
                        post_docker_commands=["docker load -i /code/busybox.tar",
                                              "docker load -i /code/calico-node-libnetwork.tar"],
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

            with self.assertRaises(Exception) as cm:
                host.execute("docker network create -d calico --ipam-driver calico-ipam --opt ipip=true shouldfailnet")

            self.assertIn("Arbitrary options are not supported", str(cm.exception))
