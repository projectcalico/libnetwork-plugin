from etcd import EtcdKeyNotFound
from pycalico.ipam import IPAMClient
import json

PREFIX = "/calico/libnetwork/v1/"


class LibnetworkDatastoreClient(IPAMClient):
    def get_network(self, network_id):
        """
        Get the data for a network ID.

        :param network_id: The network ID to read.
        :return: A python datastructure representing the JSON that libnetwork
        provided on the CreateNetwork call, or None if it couldn't be found.
        """
        try:
            network_id = self.etcd_client.read(PREFIX + network_id)
            return json.loads(network_id.value)
        except EtcdKeyNotFound:
            return None

    def write_network(self, network_id, create_network_json):
        """
        Write a network ID, recording the data that was provided by libnetwork
        on the CreateNetwork call.
        :param network_id: The network ID to write.
        :param create_network_json: Python datastructure representing the
                                    CreateNetwork data.
        :return: Nothing
        """
        self.etcd_client.write(PREFIX + network_id,
                               json.dumps(create_network_json))

    def remove_network(self, network_id):
        """
        Remove a network ID
        :param network_id: The network ID to delete.
        :return: True if the delete was successful, false if the network_id
        didn't exist.
        """
        try:
            self.etcd_client.delete(PREFIX + network_id)
        except EtcdKeyNotFound:
            return False
        else:
            return True
