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
import json
import socket
import unittest

from mock import patch, ANY, call
from netaddr import IPAddress, IPNetwork
from nose.tools import assert_equal
from pycalico.util import generate_cali_interface_name
from subprocess32 import CalledProcessError

from libnetwork import driver_plugin
from pycalico.datastore_datatypes import Endpoint, IF_PREFIX, IPPool

TEST_ENDPOINT_ID = "TEST_ENDPOINT_ID"
TEST_NETWORK_ID = "TEST_NETWORK_ID"

hostname = socket.gethostname()


class TestPlugin(unittest.TestCase):

    def setUp(self):
        self.app = driver_plugin.app.test_client()

    def tearDown(self):
        pass

    def test_404(self):
        rv = self.app.post('/')
        assert_equal(rv.status_code, 404)

    def test_activate(self):
        rv = self.app.post('/Plugin.Activate')
        activate_response = {"Implements": ["NetworkDriver"]}
        self.assertDictEqual(json.loads(rv.data), activate_response)

    def test_capabilities(self):
        rv = self.app.post('/NetworkDriver.GetCapabilities')
        capabilities_response = {"Scope": "global"}
        self.assertDictEqual(json.loads(rv.data), capabilities_response)

    @patch("libnetwork.driver_plugin.client.create_profile", autospec=True)
    @patch("libnetwork.driver_plugin.client.write_network", autospec=True)
    @patch("libnetwork.driver_plugin.client.add_ip_pool", autospec=True)
    def test_create_network(self, m_add_ip_pool, m_write_network, m_create):
        """
        Test create_network
        """
        request_json = '{"NetworkID": "%s", ' \
                       '"IPv4Data":[{"Pool": "6.5.4.3/21"}],'\
                       '"IPv6Data":[],'\
                       '"Options": {"com.docker.network.generic":{}}}' % TEST_NETWORK_ID
        rv = self.app.post('/NetworkDriver.CreateNetwork',
                           data=request_json)
        m_create.assert_called_once_with(TEST_NETWORK_ID)
        m_add_ip_pool.assert_called_once_with(4, IPPool("6.5.4.3/21"))
        m_write_network.assert_called_once_with(TEST_NETWORK_ID,
                                                json.loads(request_json))

        self.assertDictEqual(json.loads(rv.data), {})


    @patch("libnetwork.driver_plugin.client.remove_ip_pool", autospec=True)
    @patch("libnetwork.driver_plugin.client.get_network", autospec=True, return_value=None)
    @patch("libnetwork.driver_plugin.client.remove_profile", autospec=True)
    def test_delete_network(self, m_remove, m_get_network, m_remove_pool):
        """
        Test the delete_network hook correctly removes the etcd data and
        returns the correct response.
        """
        m_get_network.return_value = {"NetworkID": TEST_NETWORK_ID,
                                      "IPv4Data":[{"Pool": "6.5.4.3/21"}],
                                      "IPv6Data":[]}

        rv = self.app.post('/NetworkDriver.DeleteNetwork',
                           data='{"NetworkID": "%s"}' % TEST_NETWORK_ID)
        m_remove.assert_called_once_with(TEST_NETWORK_ID)
        m_remove_pool.assert_called_once_with(4, IPNetwork("6.5.4.3/21"))
        self.assertDictEqual(json.loads(rv.data), {})

    @patch("libnetwork.driver_plugin.client.remove_profile", autospec=True)
    def test_delete_network_no_profile(self, m_remove):
        """
        Test the delete_network hook correctly removes the etcd data and
        returns the correct response.
        """
        m_remove.side_effect = KeyError
        rv = self.app.post('/NetworkDriver.DeleteNetwork',
                           data='{"NetworkID": "%s"}' % TEST_NETWORK_ID)
        m_remove.assert_called_once_with(TEST_NETWORK_ID)
        self.assertDictEqual(json.loads(rv.data), {u'Err': u''})

    def test_oper_info(self):
        """
        Test oper_info returns the correct data.
        """
        rv = self.app.post('/NetworkDriver.EndpointOperInfo',
                           data='{"EndpointID": "%s"}' % TEST_ENDPOINT_ID)
        self.assertDictEqual(json.loads(rv.data), {"Value": {}})

    @patch("pycalico.netns.set_veth_mac", autospec=True)
    @patch("pycalico.netns.create_veth", autospec=True)
    def test_join(self, m_create_veth, m_set_mac):
        """
        Test the join() processing correctly creates the veth.
        """
        # Actually make the request to the plugin.
        rv = self.app.post('/NetworkDriver.Join',
                           data='{"EndpointID": "%s", "NetworkID": "%s"}' %
                                (TEST_ENDPOINT_ID, TEST_NETWORK_ID))

        host_interface_name = generate_cali_interface_name(IF_PREFIX, TEST_ENDPOINT_ID)
        temp_interface_name = generate_cali_interface_name("tmp", TEST_ENDPOINT_ID)

        m_create_veth.assert_called_once_with(host_interface_name, temp_interface_name)
        m_set_mac.assert_called_once_with(temp_interface_name, "EE:EE:EE:EE:EE:EE")

        expected_response = """
        {
          "Gateway": "",
          "InterfaceName": { "DstPrefix": "cali", "SrcName": "tmpTEST_ENDPOI" }
        }"""
        self.maxDiff = None
        self.assertDictEqual(json.loads(rv.data),
                             json.loads(expected_response))

    @patch("libnetwork.driver_plugin.client.get_default_next_hops", autospec=True)
    @patch("pycalico.netns.set_veth_mac", autospec=True)
    @patch("pycalico.netns.create_veth", autospec=True)
    @patch("libnetwork.driver_plugin.remove_veth", autospec=True)
    def test_join_veth_fail(self, m_del_veth, m_create_veth, m_set_veth_mac, m_next_hops):
        """
        Test the join() processing when create_veth fails.
        """
        m_create_veth.side_effect = CalledProcessError(2, "testcmd")

        m_next_hops.return_value = {4: IPAddress("1.2.3.4"),
                                    6: None}

        # Actually make the request to the plugin.
        rv = self.app.post('/NetworkDriver.Join',
                           data='{"EndpointID": "%s", "NetworkID": "%s"}' %
                                (TEST_ENDPOINT_ID, TEST_NETWORK_ID))

        # Check that create veth is called with the expected endpoint, and
        # that set_endpoint is not (since create_veth is raising an exception).
        host_interface_name = generate_cali_interface_name(IF_PREFIX, TEST_ENDPOINT_ID)
        temp_interface_name = generate_cali_interface_name("tmp", TEST_ENDPOINT_ID)

        m_create_veth.assert_called_once_with(host_interface_name, temp_interface_name)

        # Check that we delete the veth.
        m_del_veth.assert_called_once_with(host_interface_name)

        # Expect a 500 response.
        self.assertDictEqual(json.loads(rv.data), {u'Err': u"Command 'testcmd' returned non-zero exit status 2"})


    @patch("libnetwork.driver_plugin.remove_veth", autospec=True)
    def test_leave(self, m_veth):
        """
        Test leave() processing removes the veth.
        """
        # Send the leave request.
        rv = self.app.post('/NetworkDriver.Leave',
                           data='{"EndpointID": "%s"}' % TEST_ENDPOINT_ID)
        self.assertDictEqual(json.loads(rv.data), {})

        m_veth.assert_called_once_with(generate_cali_interface_name(IF_PREFIX, TEST_ENDPOINT_ID))

    @patch("libnetwork.driver_plugin.client.remove_endpoint", autospec=True)
    def test_delete_endpoint(self, m_remove):
        """
        Test delete_endpoint() deletes the endpoint and backout IP assignment.
        """
        rv = self.app.post('/NetworkDriver.DeleteEndpoint',
                           data='{"EndpointID": "%s"}' % TEST_ENDPOINT_ID)
        m_remove.assert_called_once_with(Endpoint(hostname,
                                                  "libnetwork",
                                                  "docker",
                                                  TEST_ENDPOINT_ID,
                                                  None,
                                                  None))
        self.assertDictEqual(json.loads(rv.data), {})

    @patch("libnetwork.driver_plugin.client.remove_endpoint", autospec=True,  side_effect=KeyError())
    def test_delete_endpoint_fail(self, m_remove):
        """
        Test delete_endpoint() deletes the endpoint and backout IP assignment.
        """
        rv = self.app.post('/NetworkDriver.DeleteEndpoint',
                           data='{"EndpointID": "%s"}' % TEST_ENDPOINT_ID)
        m_remove.assert_called_once_with(Endpoint(hostname,
                                                  "libnetwork",
                                                  "docker",
                                                  TEST_ENDPOINT_ID,
                                                  None,
                                                  None))
        self.assertDictEqual(json.loads(rv.data), {u'Err': u''})


    @patch("libnetwork.driver_plugin.client.get_network", autospec=True, return_value=None)
    def test_create_endpoint_missing_network(self, _):
        """
        Test the create_endpoint hook behavior when missing network data.
        """
        rv = self.app.post('/NetworkDriver.CreateEndpoint', data="""
                           {"EndpointID": "%s",
                            "NetworkID":  "%s",
                            "Interface": {"MacAddress": "EE:EE:EE:EE:EE:EE",
                                          "Address": "1.2.3.4/32"
                            }}""" %
                                    (TEST_ENDPOINT_ID, TEST_NETWORK_ID))
        expected_data = { u'Err': u"CreateEndpoint called but network doesn't "
                                  u"exist Endpoint ID: TEST_ENDPOINT_ID "
                                  u"Network ID: TEST_NETWORK_ID"}
        self.assertDictEqual(json.loads(rv.data), expected_data)

    @patch("libnetwork.driver_plugin.client.get_network", autospec=True)
    @patch("libnetwork.driver_plugin.client.set_endpoint", autospec=True)
    def test_create_endpoint(self, m_set, m_get_network):
        """
        Test the create_endpoint hook correctly writes the appropriate data
        to etcd based on IP assignment.
        """

        # Iterate using various different mixtures of IP assignments.
        # (IPv4 addr, IPv6 addr)
        parms = [(None, IPAddress("aa:bb::bb")),
                 (IPAddress("10.20.30.40"), None),
                 (IPAddress("10.20.30.40"), IPAddress("aa:bb::bb"))]

        m_get_network.return_value = {"NetworkID": TEST_NETWORK_ID,
                                      "IPv4Data":[{"Gateway": "6.5.4.3"}],
                                      "IPv6Data":[{"Gateway": "aa:bb::cc"}]}

        # Loop through different combinations of IP availability.
        for ipv4,  ipv6 in parms:
            ipv4_json = ',"Address": "%s"' % ipv4 if ipv4 else ""
            ipv6_json = ',"AddressIPv6": "%s"' % ipv6 if ipv6 else ""

            # Invoke create endpoint.
            rv = self.app.post('/NetworkDriver.CreateEndpoint',
                               data='{"EndpointID": "%s",'
                                     '"NetworkID":  "%s",'
                                     '"Interface": {"MacAddress": "EE:EE:EE:EE:EE:EE"%s%s}}' %
                                    (TEST_ENDPOINT_ID, TEST_NETWORK_ID, ipv4_json, ipv6_json))


            # Assert expected data is written to etcd
            ep = Endpoint(hostname, "libnetwork", "libnetwork",
                          TEST_ENDPOINT_ID, "active", "EE:EE:EE:EE:EE:EE")

            ep.profile_ids.append(TEST_NETWORK_ID)

            if ipv4:
                ep.ipv4_nets.add(IPNetwork(ipv4))
                ep.ipv4_gateway = IPAddress("6.5.4.3")

            if ipv6:
                ep.ipv6_nets.add(IPNetwork(ipv6))
                ep.ipv6_gateway = IPAddress("aa:bb::cc")

            m_set.assert_called_once_with(ep)


            # Assert return value
            self.assertDictEqual(json.loads(rv.data), {
                "Interface": {
                    "MacAddress": "EE:EE:EE:EE:EE:EE"
                }
            })

            # Reset the Mocks before continuing.
            m_set.reset_mock()

    def test_discover_new(self):
        """
        Test discover_new returns the correct data.
        """
        rv = self.app.post('/NetworkDriver.DiscoverNew',
                           data='{"DiscoveryType": 1,'
                                 '"DiscoveryData": {'
                                    '"Address": "thisaddress",'
                                    '"self": true'
                                  '}'
                                '}')
        self.assertDictEqual(json.loads(rv.data), {})

    def test_discover_delete(self):
        """
        Test discover_delete returns the correct data.
        """
        rv = self.app.post('/NetworkDriver.DiscoverDelete',
                           data='{"DiscoveryType": 1,'
                                 '"DiscoveryData": {'
                                    '"Address": "thisaddress",'
                                    '"self": true'
                                  '}'
                                '}')
        self.assertDictEqual(json.loads(rv.data), {})

    @patch("pycalico.netns.remove_veth", autospec=True, side_effect=CalledProcessError(2, "test"))
    def test_remove_veth_fail(self, m_remove):
        """
        Test remove_veth calls through to netns to remove the veth.
        Fail with a CalledProcessError to write the log.
        """
        name = generate_cali_interface_name(IF_PREFIX, TEST_ENDPOINT_ID)

        driver_plugin.remove_veth(name)
        m_remove.assert_called_once_with(name)

