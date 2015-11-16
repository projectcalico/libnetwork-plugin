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

from unittest import skip
from mock import patch, ANY, call
from netaddr import IPAddress, IPNetwork
from nose.tools import assert_equal
from pycalico.util import generate_cali_interface_name
from subprocess32 import CalledProcessError

from libnetwork import driver_plugin
from pycalico.datastore_datatypes import Endpoint, IF_PREFIX, IPPool
from pycalico.datastore_errors import PoolNotFound

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
        activate_response = {"Implements": ["NetworkDriver", "IpamDriver"]}
        self.assertDictEqual(json.loads(rv.data), activate_response)

    def test_get_default_address_spaces(self):
        """
        Test get_default_address_spaces returns the fixed values.
        """
        rv = self.app.post('/IpamDriver.GetDefaultAddressSpaces')
        response_data = {
            "LocalDefaultAddressSpace": "CalicoLocalAddressSpace",
            "GlobalDefaultAddressSpace": "CalicoGlobalAddressSpace"
        }
        self.assertDictEqual(json.loads(rv.data), response_data)

    def test_request_pool_v4(self):
        """
        Test request_pool returns the correct fixed values for IPv4.
        """
        request_data = {
            "Pool": "",
            "SubPool": "",
            "V6": False
        }
        rv = self.app.post('/IpamDriver.RequestPool',
                           data=json.dumps(request_data))
        response_data = {
            "PoolID": "CalicoPoolIPv4",
            "Pool": "0.0.0.0/0",
            "Data": {
                "com.docker.network.gateway": "0.0.0.0/0"
            }
        }
        self.assertDictEqual(json.loads(rv.data), response_data)

    def test_request_pool_v6(self):
        """
        Test request_pool returns the correct fixed values for IPv6.
        """
        request_data = {
            "Pool": "",
            "SubPool": "",
            "V6": True
        }
        rv = self.app.post('/IpamDriver.RequestPool',
                           data=json.dumps(request_data))
        response_data = {
            "PoolID": "CalicoPoolIPv6",
            "Pool": "::/0",
            "Data": {
                "com.docker.network.gateway": "::/0"
            }
        }
        self.assertDictEqual(json.loads(rv.data), response_data)

    def test_request_pool_pool_defined(self):
        """
        Test request_pool errors if a specific pool is requested.
        """
        request_data = {
            "Pool": "1.2.3.4/5",
            "SubPool": "",
            "V6": False
        }
        rv = self.app.post('/IpamDriver.RequestPool',
                           data=json.dumps(request_data))
        self.assertTrue("Err" in json.loads(rv.data))

    def test_request_pool_subpool_defined(self):
        """
        Test request_pool errors if a specific sub-pool is requested.
        """
        request_data = {
            "Pool": "",
            "SubPool": "1.2.3.4/5",
            "V6": False
        }
        rv = self.app.post('/IpamDriver.RequestPool',
                           data=json.dumps(request_data))
        self.assertTrue("Err" in json.loads(rv.data))

    def test_release_pool(self):
        """
        Test release_pool.
        """
        request_data = {
            "PoolID": "TestPoolID",
        }
        rv = self.app.post('/IpamDriver.ReleasePool',
                           data=json.dumps(request_data))
        self.assertDictEqual(json.loads(rv.data), {})

    @patch("libnetwork.driver_plugin.client.auto_assign_ips", autospec=True)
    def test_request_address_auto_assign(self, m_auto_assign):
        """
        Test request_address when address is auto-assigned.
        """
        request_data = {
            "PoolID": "CalicoPoolIPv6",
            "Address": ""
        }
        ip = IPAddress("aa::ff")
        m_auto_assign.return_value = ([], [ip])
        rv = self.app.post('/IpamDriver.RequestAddress',
                           data=json.dumps(request_data))
        response_data = {
            "Address": str(IPNetwork(ip)),
            "Data": {}
        }
        self.assertDictEqual(json.loads(rv.data), response_data)

    @patch("libnetwork.driver_plugin.client.auto_assign_ips", autospec=True)
    def test_request_address_auto_assign_no_ips(self, m_auto_assign):
        """
        Test request_address when there are no auto assigned IPs.
        """
        request_data = {
            "PoolID": "CalicoPoolIPv6",
            "Address": ""
        }
        m_auto_assign.return_value = ([], [])
        rv = self.app.post('/IpamDriver.RequestAddress',
                           data=json.dumps(request_data))
        self.assertTrue("Err" in json.loads(rv.data))

    @patch("libnetwork.driver_plugin.client.assign_ip", autospec=True)
    def test_request_address_ip_supplied(self, m_assign):
        """
        Test request_address when address is supplied.
        """
        ip = IPAddress("1.2.3.4")
        request_data = {
            "PoolID": "CalicoPoolIPv4",
            "Address": str(ip)
        }
        m_assign.return_value = True
        rv = self.app.post('/IpamDriver.RequestAddress',
                           data=json.dumps(request_data))
        response_data = {
            "Address": str(IPNetwork(ip)),
            "Data": {}
        }
        self.assertDictEqual(json.loads(rv.data), response_data)

    @patch("libnetwork.driver_plugin.client.assign_ip", autospec=True)
    def test_request_address_ip_supplied_in_use(self, m_assign):
        """
        Test request_address when the supplied address is in use.
        """
        ip = IPAddress("1.2.3.4")
        request_data = {
            "PoolID": "CalicoPoolIPv4",
            "Address": str(ip)
        }
        m_assign.return_value = False
        rv = self.app.post('/IpamDriver.RequestAddress',
                           data=json.dumps(request_data))
        self.assertTrue("Err" in json.loads(rv.data))

    @patch("libnetwork.driver_plugin.client.assign_ip", autospec=True)
    def test_request_address_ip_supplied_no_pool(self, m_assign):
        """
        Test request_address when the supplied address is not in a pool.
        """
        ip = IPAddress("1.2.3.4")
        request_data = {
            "PoolID": "CalicoPoolIPv4",
            "Address": str(ip)
        }
        m_assign.side_effect = PoolNotFound(ip)
        rv = self.app.post('/IpamDriver.RequestAddress',
                           data=json.dumps(request_data))
        self.assertTrue("Err" in json.loads(rv.data))

    @patch("libnetwork.driver_plugin.client.release_ips", autospec=True)
    def test_release_address(self, m_release):
        """
        Test request_address when address is supplied.
        """
        ip = IPAddress("1.2.3.4")
        request_data = {
            "Address": str(ip)
        }
        rv = self.app.post('/IpamDriver.ReleaseAddress',
                           data=json.dumps(request_data))
        self.assertDictEqual(json.loads(rv.data), {})
        m_release.assert_called_once_with({ip})

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
        request_data = {
            "NetworkID": TEST_NETWORK_ID,
            "IPv4Data": [{
                "Gateway": "10.0.0.0/8",
                "Pool": "6.5.4.3/21"
            }],
            "IPv6Data": [],
            "Options": {
                "com.docker.network.generic": {}
            }
        }
        rv = self.app.post('/NetworkDriver.CreateNetwork',
                           data=json.dumps(request_data))
        m_create.assert_called_once_with(TEST_NETWORK_ID)
        m_add_ip_pool.assert_called_once_with(4,
                                              IPPool("6.5.4.3/21", ipam=False))
        m_write_network.assert_called_once_with(TEST_NETWORK_ID,
                                                request_data)

        self.assertDictEqual(json.loads(rv.data), {})


    @patch("libnetwork.driver_plugin.client.remove_network", autospec=True)
    @patch("libnetwork.driver_plugin.client.remove_ip_pool", autospec=True)
    @patch("libnetwork.driver_plugin.client.get_network", autospec=True)
    @patch("libnetwork.driver_plugin.client.remove_profile", autospec=True)
    def test_delete_network_default_ipam(self, m_remove_profile, m_get_network,
                                         m_remove_pool, m_remove_network):
        """
        Test the delete_network behavior for default IPAM.
        """
        m_get_network.return_value = {
            "NetworkID": TEST_NETWORK_ID,
            "IPv4Data": [{
                "Gateway": "6.5.4.3/21",
                "Pool": "6.5.4.3/21"
            }],
            "IPv6Data": [{
                "Gateway": "aa::ff/10",
                "Pool": "aa::fe/10"
            }]
        }

        request_data = {
            "NetworkID": TEST_NETWORK_ID
        }

        rv = self.app.post('/NetworkDriver.DeleteNetwork',
                           data=json.dumps(request_data))
        m_remove_profile.assert_called_once_with(TEST_NETWORK_ID)
        m_remove_network.assert_called_once_with(TEST_NETWORK_ID)
        m_remove_pool.assert_has_calls([call(4, IPNetwork("6.5.4.3/21")),
                                        call(6, IPNetwork("aa::fe/10"))])
        self.assertDictEqual(json.loads(rv.data), {})

    @patch("libnetwork.driver_plugin.client.remove_network", autospec=True)
    @patch("libnetwork.driver_plugin.client.remove_ip_pool", autospec=True)
    @patch("libnetwork.driver_plugin.client.get_network", autospec=True, return_value=None)
    @patch("libnetwork.driver_plugin.client.remove_profile", autospec=True)
    def test_delete_network_calico_ipam(self, m_remove_profile, m_get_network,
                                        m_remove_pool, m_remove_network):
        """
        Test the delete_network behavior for Calico IPAM.
        """
        m_get_network.return_value = {
            "NetworkID": TEST_NETWORK_ID,
            "IPv4Data": [{
                "Gateway": "0.0.0.0/0",
                "Pool": "0.0.0.0/0"
            }],
            "IPv6Data": [{
                "Gateway": "00::00/0",
                "Pool": "00::00/0"
            }]
        }

        request_data = {
            "NetworkID": TEST_NETWORK_ID
        }

        rv = self.app.post('/NetworkDriver.DeleteNetwork',
                           data=json.dumps(request_data))
        m_remove_profile.assert_called_once_with(TEST_NETWORK_ID)
        m_remove_network.assert_called_once_with(TEST_NETWORK_ID)
        self.assertEquals(m_remove_pool.call_count, 0)
        self.assertDictEqual(json.loads(rv.data), {})

    @patch("libnetwork.driver_plugin.client.remove_profile", autospec=True)
    def test_delete_network_no_profile(self, m_remove):
        """
        Test the delete_network hook correctly removes the etcd data and
        returns the correct response.
        """
        m_remove.side_effect = KeyError
        request_data = {
            "NetworkID": TEST_NETWORK_ID
        }
        rv = self.app.post('/NetworkDriver.DeleteNetwork',
                           data=json.dumps(request_data))
        m_remove.assert_called_once_with(TEST_NETWORK_ID)
        self.assertDictEqual(json.loads(rv.data), {u'Err': u''})

    def test_oper_info(self):
        """
        Test oper_info returns the correct data.
        """
        request_data = {
            "EndpointID": TEST_ENDPOINT_ID
        }
        rv = self.app.post('/NetworkDriver.EndpointOperInfo',
                           data=json.dumps(request_data))
        self.assertDictEqual(json.loads(rv.data), {"Value": {}})

    @patch("libnetwork.driver_plugin.client.get_network", autospec=True)
    @patch("pycalico.netns.set_veth_mac", autospec=True)
    @patch("pycalico.netns.create_veth", autospec=True)
    def test_join_default_ipam(self, m_create_veth, m_set_mac, m_get_network):
        """
        Test the join() processing with default IPAM.
        """
        request_data = {
            "EndpointID": TEST_ENDPOINT_ID,
            "NetworkID": TEST_NETWORK_ID
        }

        m_get_network.return_value = {
            "NetworkID": TEST_NETWORK_ID,
            "IPv4Data": [{
                "Gateway": "6.5.4.3/21",
                "Pool": "6.5.4.3/21"
            }],
            "IPv6Data": []}

        # Actually make the request to the plugin.
        rv = self.app.post('/NetworkDriver.Join',
                           data=json.dumps(request_data))

        # Check the expected response.
        response_data = {
            "Gateway": "",
            "GatewayIPv6": "",
            "InterfaceName": {
                "DstPrefix": "cali",
                "SrcName": "tmpTEST_ENDPOI"
            }
        }
        self.maxDiff = None
        self.assertDictEqual(json.loads(rv.data), response_data)

        # Check appropriate netns calls.
        host_interface_name = generate_cali_interface_name(IF_PREFIX, TEST_ENDPOINT_ID)
        temp_interface_name = generate_cali_interface_name("tmp", TEST_ENDPOINT_ID)

        m_create_veth.assert_called_once_with(host_interface_name, temp_interface_name)
        m_set_mac.assert_called_once_with(temp_interface_name, "EE:EE:EE:EE:EE:EE")


    @patch("libnetwork.driver_plugin.client.get_endpoint", autospec=True)
    @patch("libnetwork.driver_plugin.client.get_network", autospec=True, return_value=None)
    @patch("pycalico.netns.set_veth_mac", autospec=True)
    @patch("pycalico.netns.create_veth", autospec=True)
    def test_join_calico_ipam(self, m_create_veth, m_set_mac, m_get_network,
                              m_get_endpoint):
        """
        Test the join() processing with Calico IPAM.
        """
        m_get_network.return_value = {
            "NetworkID": TEST_NETWORK_ID,
            "IPv4Data":[{
                "Gateway": "0.0.0.0/0",
                "Pool": "0.0.0.0/0"
            }],
            "IPv6Data":[{
                "Gateway": "::/0",
                "Pool": "::/0"
            }]}
        m_get_endpoint.return_value = Endpoint(hostname,
                                               "libnetwork",
                                               "docker",
                                               TEST_ENDPOINT_ID,
                                               None,
                                               None)
        m_get_endpoint.return_value.ipv4_gateway = IPAddress("1.2.3.4")
        m_get_endpoint.return_value.ipv6_gateway = IPAddress("aa::ff")

        # Actually make the request to the plugin.
        rv = self.app.post('/NetworkDriver.Join',
                           data='{"EndpointID": "%s", "NetworkID": "%s"}' %
                                (TEST_ENDPOINT_ID, TEST_NETWORK_ID))

        host_interface_name = generate_cali_interface_name(IF_PREFIX, TEST_ENDPOINT_ID)
        temp_interface_name = generate_cali_interface_name("tmp", TEST_ENDPOINT_ID)

        m_create_veth.assert_called_once_with(host_interface_name, temp_interface_name)
        m_set_mac.assert_called_once_with(temp_interface_name, "EE:EE:EE:EE:EE:EE")

        expected_data = {
            "Gateway": str(m_get_endpoint.return_value.ipv4_gateway),
            "GatewayIPv6": str(m_get_endpoint.return_value.ipv6_gateway),
            "InterfaceName": {
                "DstPrefix": "cali",
                "SrcName": "tmpTEST_ENDPOI"
            },
            "StaticRoutes": [{
                "Destination": str(m_get_endpoint.return_value.ipv4_gateway) +"/32",
                "RouteType": 1,
                "NextHop": ""
            }, {
                "Destination": str(m_get_endpoint.return_value.ipv6_gateway) + "/128",
                "RouteType": 1,
                "NextHop": ""
            }]
        }
        self.maxDiff = None
        self.assertDictEqual(json.loads(rv.data),
                             expected_data)

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

        # Expect a 500 response.
        self.assertDictEqual(json.loads(rv.data), {u'Err': u"Command 'testcmd' returned non-zero exit status 2"})

        # Check that create veth is called with the expected endpoint, and
        # that set_endpoint is not (since create_veth is raising an exception).
        host_interface_name = generate_cali_interface_name(IF_PREFIX, TEST_ENDPOINT_ID)
        temp_interface_name = generate_cali_interface_name("tmp", TEST_ENDPOINT_ID)

        m_create_veth.assert_called_once_with(host_interface_name, temp_interface_name)

        # Check that we delete the veth.
        m_del_veth.assert_called_once_with(host_interface_name)

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
        expected_data = { u'Err': u"Network TEST_NETWORK_ID does not exist"}
        self.assertDictEqual(json.loads(rv.data), expected_data)

    @patch("libnetwork.driver_plugin.client.get_default_next_hops", autospec=True)
    @patch("libnetwork.driver_plugin.client.get_network", autospec=True)
    @patch("libnetwork.driver_plugin.client.set_endpoint", autospec=True)
    def test_create_endpoint(self, m_set, m_get_network, m_get_next_hops):
        """
        Test the create_endpoint hook correctly writes the appropriate data
        to etcd based on IP assignment and pool selection.
        """

        # Iterate using various different mixtures of IP assignments and
        # gateway CIDRs.
        #
        # (IPv4 addr, IPv6 addr, IPv4 gway, IPv6 gway, calico_ipam)
        #
        # calico_ipam indicates whether the gateway indicates Calico IPAM or
        # not which changes the gateway selected in the endpoint.
        parms = [(None, "aa:bb::bb", None, "cc:dd::00/23", False),
                 ("10.20.30.40", None, "1.2.3.4/32", "aa:bb:cc::/24", False),
                 ("20.20.30.40", "ab:bb::bb", "1.2.3.4/32", "aa:bb:cc::/25", False),
                 (None, "ac:bb::bb", None, "00::00/0", True),
                 ("40.20.30.40", None, "0.0.0.0/0", "::/0", True),
                 ("50.20.30.40", "ad:bb::bb", "0.0.0.0/0", "00::/0", True)]

        next_hop_4 = IPAddress("11.22.33.44")
        next_hop_6 = IPAddress("a0:b0::f0")
        m_get_next_hops.return_value = {4: next_hop_4,
                                        6: next_hop_6}

        # Loop through different combinations of IP availability.
        for ipv4, ipv6, gwv4, gwv6, calico_ipam in parms:
            m_get_network.return_value = {
                "NetworkID": TEST_NETWORK_ID,
                "IPv4Data":[{"Gateway": gwv4, "Pool": gwv4}],
                "IPv6Data":[{"Gateway": gwv6, "Pool": gwv6}]
            }
            ipv4_json = ',"Address": "%s"' % ipv4 if ipv4 else ""
            ipv6_json = ',"AddressIPv6": "%s"' % ipv6 if ipv6 else ""

            # Invoke create endpoint.
            rv = self.app.post('/NetworkDriver.CreateEndpoint',
                               data='{"EndpointID": "%s",'
                                     '"NetworkID":  "%s",'
                                     '"Interface": {"MacAddress": "EE:EE:EE:EE:EE:EE"%s%s}}' %
                                    (TEST_ENDPOINT_ID, TEST_NETWORK_ID, ipv4_json, ipv6_json))

            # Assert return value
            self.assertDictEqual(json.loads(rv.data), {
                "Interface": {
                    "MacAddress": "EE:EE:EE:EE:EE:EE"
                }
            })

            # Assert expected data is written to etcd
            ep = Endpoint(hostname, "libnetwork", "libnetwork",
                          TEST_ENDPOINT_ID, "active", "EE:EE:EE:EE:EE:EE")

            ep.profile_ids.append(TEST_NETWORK_ID)

            if ipv4:
                ep.ipv4_nets.add(IPNetwork(ipv4))
                if calico_ipam:
                    ep.ipv4_gateway = next_hop_4
                else:
                    ep.ipv4_gateway = IPNetwork(gwv4).ip

            if ipv6:
                ep.ipv6_nets.add(IPNetwork(ipv6))
                if calico_ipam:
                    ep.ipv6_gateway = next_hop_6
                else:
                    ep.ipv6_gateway = IPNetwork(gwv6).ip

            m_set.assert_called_once_with(ep)

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

    def test_get_gateway_pool_from_network_data(self):
        """
        Test get_gateway_pool_from_network_data for a variety of inputs.
        """
        tests = [
            (
                (None, None), 4, {
                    "IPv6Data": []
                }
            ),
            (
                (None, None), 6, {
                    "IPv6Data": []
                }
            ),
            (
                (None, None), 6, {
                    "IPv6Data": [{}]
                }
            ),
            (
                (None, None), 4, {
                    "IPv4Data": [{
                        "Gateway": "1.2.3.4/40"
                    }]
                }
            ),
            (
                (None, None), 4, {
                    "IPv4Data": [{
                        "Pool": "1.2.3.4/40"
                    }]
                }
            ),
            (
                (IPNetwork("aa::ff/120"), IPNetwork("aa::dd/121")), 6, {
                    "IPv6Data": [{
                        "Gateway": "aa::ff/120",
                        "Pool": "aa::dd/121"
                    }]
                }
            )]

        for result, version, network_data in tests:
            self.assertEquals(
                driver_plugin.get_gateway_pool_from_network_data(network_data,
                                                                 version),
                result
            )

    def test_get_gateway_pool_from_network_data_multiple_datas(self):
        """
        Test get_gateway_pool_from_network_data when multiple data blocks are
        supplied.
        """
        network_data = {
                    "IPv6Data": [{
                        "Gateway": "aa::ff/120",
                        "Pool": "aa::dd/121"
                    }, {
                        "Gateway": "aa::fa/120",
                        "Pool": "aa::da/121"
                    }]
                }
        self.assertRaises(Exception,
                          driver_plugin.get_gateway_pool_from_network_data,
                          network_data, 6)

    def test_is_using_calico_ipam(self):
        """
        Test is_using_calico_ipam using a variety of CIDRs.
        """
        for cidr, is_cipam in [(IPNetwork("1.2.3.4/20"), False),
                               (IPNetwork("0.0.0.0/20"), False),
                               (IPNetwork("::/128"), False),
                               (IPNetwork("0.0.0.0/32"), False),
                               (IPNetwork("0.0.0.0/0"), True),
                               (IPNetwork("::/0"), True)]:
            self.assertEquals(driver_plugin.is_using_calico_ipam(cidr),
                              is_cipam)
