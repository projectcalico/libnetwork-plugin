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
import unittest

from etcd import EtcdKeyNotFound
from etcd import Client as EtcdClient
from mock import patch, ANY, call, Mock
from netaddr import IPAddress, IPNetwork
from nose.tools import assert_equal
from pycalico import datastore

from libnetwork.datastore_libnetwork import LibnetworkDatastoreClient

TEST_NETWORK_ID = "ABCDEFGHJSDHFLA"
TEST_NETWORK_DIR = "/calico/libnetwork/v1/" + TEST_NETWORK_ID
TEST_DATA = {"test": 1234, "test2": [1, 2, 3, 4]}
TEST_JSON = json.dumps(TEST_DATA)

class TestLibnetworkDatastoreClient(unittest.TestCase):

    @patch("pycalico.datastore.os.getenv", autospec=True)
    @patch("pycalico.datastore.etcd.Client", autospec=True)
    def setUp(self, m_etcd_client, m_getenv):
        def get_env(key, default=""):
            if key == "ETCD_AUTHORITY":
                return "127.0.0.2:4002"
            else:
                return default
        m_getenv.side_effect = get_env
        self.etcd_client = Mock(spec=EtcdClient)
        m_etcd_client.return_value = self.etcd_client
        self.datastore = LibnetworkDatastoreClient()
        m_etcd_client.assert_called_once_with(host="127.0.0.2", port=4002,
                                              protocol="http", cert=None,
                                              ca_cert=None)

    def tearDown(self):
        pass

    def test_get_network(self):
        """
        Test get_network() returns correct data.
        :return:
        """
        etcd_entry = Mock()
        etcd_entry.value = TEST_JSON
        self.etcd_client.read.return_value = etcd_entry
        self.assertDictEqual(self.datastore.get_network(TEST_NETWORK_ID),
                             TEST_DATA)
        self.etcd_client.read.assert_called_once_with(TEST_NETWORK_DIR)

    def test_get_network_not_found(self):
        """
        Test get_network() returns None when the network is not found.
        :return:
        """
        self.etcd_client.read.side_effect = EtcdKeyNotFound
        self.assertEquals(self.datastore.get_network(TEST_NETWORK_ID), None)
        self.etcd_client.read.assert_called_once_with(TEST_NETWORK_DIR)

    def test_write_network(self):
        """
        Test write_network() sends correct data to etcd.
        """
        test_data = TEST_DATA
        self.datastore.write_network(TEST_NETWORK_ID, test_data)
        self.etcd_client.write.assert_called_once_with(TEST_NETWORK_DIR,
                                                       TEST_JSON)

    def test_remove_network(self):
        """
        Test remove_network() when the network is present.
        """
        self.assertTrue(self.datastore.remove_network(TEST_NETWORK_ID))
        self.etcd_client.delete.assert_called_once_with(TEST_NETWORK_DIR)

    def test_remove_network_not_found(self):
        """
        Test remove_network() when the network is not found.
        """
        self.etcd_client.delete.side_effect = EtcdKeyNotFound
        self.assertFalse(self.datastore.remove_network(TEST_NETWORK_ID))
        self.etcd_client.delete.assert_called_once_with(TEST_NETWORK_DIR)
