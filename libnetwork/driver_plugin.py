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
from flask import Flask, jsonify, request
import socket
import logging
import sys

from pycalico.util import generate_cali_interface_name
from subprocess32 import CalledProcessError
from werkzeug.exceptions import HTTPException, default_exceptions
from netaddr import IPNetwork
from pycalico.datastore_datatypes import IF_PREFIX, Endpoint, IPPool
from pycalico import netns

from datastore_libnetwork import LibnetworkDatastoreClient

FIXED_MAC = "EE:EE:EE:EE:EE:EE"
CONTAINER_NAME = "libnetwork"
ORCHESTRATOR_ID = "libnetwork"

# How long to wait (seconds) for IP commands to complete.
IP_CMD_TIMEOUT = 5

hostname = socket.gethostname()
client = LibnetworkDatastoreClient()

# Return all errors as JSON. From http://flask.pocoo.org/snippets/83/
# This ensures that uncaught exceptions get returned to libnetwork in a useful
# way
def make_json_app(import_name, **kwargs):
    """
    Creates a JSON-oriented Flask app.

    All error responses that you don't specifically
    manage yourself will have application/json content
    type, and will contain JSON like this (just an example):

    { "Err": "405: Method Not Allowed" }
    """
    def make_json_error(ex):
        response = jsonify({"Err": str(ex)})
        response.status_code = (ex.code
                                if isinstance(ex, HTTPException)
                                else 500)
        return response

    wrapped_app = Flask(import_name, **kwargs)

    for code in default_exceptions.iterkeys():
        wrapped_app.error_handler_spec[None][code] = make_json_error

    return wrapped_app

app = make_json_app(__name__)
app.logger.addHandler(logging.StreamHandler(sys.stdout))
app.logger.setLevel(logging.DEBUG)
app.logger.info("Application started")

# The API calls below are documented at
# https://github.com/docker/libnetwork/blob/master/docs/remote.md


@app.route('/Plugin.Activate', methods=['POST'])
def activate():
    json_response = {"Implements": ["NetworkDriver"]}
    app.logger.debug("Activate response JSON=%s", json_response)
    return jsonify(json_response)


@app.route('/NetworkDriver.GetCapabilities', methods=['POST'])
def get_capabilities():
    json_response = {"Scope": "global"}
    app.logger.debug("GetCapabilities response JSON=%s", json_response)
    return jsonify(json_response)


@app.route('/NetworkDriver.CreateNetwork', methods=['POST'])
def create_network():
    # force is required since the request doesn't have the correct mimetype
    # If the JSON is malformed, then a BadRequest exception is raised,
    # which returns a HTTP 400 response.
    json_data = request.get_json(force=True)
    app.logger.debug("CreateNetwork JSON=%s", json_data)

    # Create the CNM "network" as a Calico profile.
    network_id = json_data["NetworkID"]
    app.logger.info("Creating profile %s", network_id)
    client.create_profile(network_id)

    # The generic options are always passed in
    options = json_data["Options"]["com.docker.network.generic"]
    ipip = options.get("ipip")
    masquerade = options.get("nat-outgoing")

    # Create a calico Pool for the CNM pool that was passed in.
    for version in (4, 6):
        ip_data = json_data["IPv%sData" % version]
        if ip_data:
            client.add_ip_pool(version, IPPool(ip_data[0]['Pool'],
                                               ipip=ipip,
                                               masquerade=masquerade))

    # Store off the JSON passed in on this request. It's required in later calls
    # - CreateEndpoint needs it for the gateway address.
    # - DeleteNetwork needs it to clean up the pool.
    client.write_network(network_id, json_data)

    app.logger.debug("CreateNetwork response JSON=%s", "{}")
    return jsonify({})


@app.route('/NetworkDriver.CreateEndpoint', methods=['POST'])
def create_endpoint():
    json_data = request.get_json(force=True)
    app.logger.debug("CreateEndpoint JSON=%s", json_data)
    endpoint_id = json_data["EndpointID"]
    network_id = json_data["NetworkID"]
    interface = json_data["Interface"]

    app.logger.info("Creating endpoint %s", endpoint_id)

    # Get the addresses to use from the request JSON.
    address_ip4 = interface.get("Address")
    address_ip6 = interface.get("AddressIPv6")
    assert address_ip4 or address_ip6

    # Get the gateway from the data passed in during CreateNetwork
    network_data = client.get_network(network_id)

    if not network_data:
        error_message = "CreateEndpoint called but network doesn't exist" \
                        " Endpoint ID: %s Network ID: %s" % \
                        (endpoint_id, network_id)
        app.logger.error(error_message)
        raise Exception(error_message)

    # Create a Calico endpoint object.
    ep = Endpoint(hostname, ORCHESTRATOR_ID, CONTAINER_NAME, endpoint_id,
                  "active", FIXED_MAC)
    ep.profile_ids.append(network_id)

    if address_ip4:
        ep.ipv4_nets.add(IPNetwork(address_ip4))
        gateway_net = IPNetwork(network_data['IPv4Data'][0]['Gateway'])
        ep.ipv4_gateway = gateway_net.ip

    if address_ip6:
        ep.ipv6_nets.add(IPNetwork(address_ip6))
        gateway_net = IPNetwork(network_data['IPv6Data'][0]['Gateway'])
        ep.ipv6_gateway = gateway_net.ip

    client.set_endpoint(ep)

    json_response = {
        "Interface": {
            "MacAddress": FIXED_MAC,
        }
    }

    app.logger.debug("CreateEndpoint response JSON=%s", json_response)
    return jsonify(json_response)


@app.route('/NetworkDriver.Join', methods=['POST'])
def join():
    json_data = request.get_json(force=True)
    app.logger.debug("Join JSON=%s", json_data)
    endpoint_id = json_data["EndpointID"]
    app.logger.info("Joining endpoint %s", endpoint_id)

    # The host interface name matches the name given when creating the endpoint
    # during CreateEndpoint
    host_interface_name = generate_cali_interface_name(IF_PREFIX, endpoint_id)

    # The temporary interface name is what gets passed to libnetwork.
    # Libnetwork renames the interface using the DstPrefix (e.g. cali0)
    temp_interface_name = generate_cali_interface_name("tmp", endpoint_id)

    try:
        # Create the veth pair.
        netns.create_veth(host_interface_name, temp_interface_name)

        # Set the mac as libnetwork doesn't do this for us (even if we return
        # it on the CreateNetwork)
        netns.set_veth_mac(temp_interface_name, FIXED_MAC)
    except CalledProcessError as e:
        # Failed to create or configure the veth, ensure veth is removed.
        remove_veth(host_interface_name)
        raise e

    json_response = {
        "InterfaceName": {
            "SrcName": temp_interface_name,
            "DstPrefix": IF_PREFIX,
        },
        "Gateway": "",  # Leave gateway empty to trigger auto-gateway behaviour
    }

    app.logger.debug("Join Response JSON=%s", json_response)
    return jsonify(json_response)


@app.route('/NetworkDriver.EndpointOperInfo', methods=['POST'])
def endpoint_oper_info():
    json_data = request.get_json(force=True)
    app.logger.debug("EndpointOperInfo JSON=%s", json_data)
    endpoint_id = json_data["EndpointID"]
    app.logger.info("Endpoint operation info requested for %s", endpoint_id)
    json_response = {
        "Value": {
        }
    }
    app.logger.debug("EP Oper Info Response JSON=%s", json_response)
    return jsonify(json_response)


@app.route('/NetworkDriver.DeleteNetwork', methods=['POST'])
def delete_network():
    json_data = request.get_json(force=True)
    app.logger.debug("DeleteNetwork JSON=%s", json_data)

    network_id = json_data["NetworkID"]

    # Remove the network. We don't raise an error if the profile is still
    # being used by endpoints. We assume libnetwork will enforce this.
    # From https://github.com/docker/libnetwork/blob/master/docs/design.md
    #   LibNetwork will not allow the delete to proceed if there are any
    #   existing endpoints attached to the Network.
    client.remove_profile(network_id)
    app.logger.info("Removed profile %s", network_id)

    # Remove the pool that was created for this network.
    json_data = client.get_network(network_id)
    for version in (4, 6):
        if json_data["IPv%sData" % version]:
            pool = IPNetwork(json_data["IPv%sData" % version][0]['Pool'])
            client.remove_ip_pool(version, pool)
            app.logger.info("Removed pool %s", pool)

    # Clean up the stored network data.
    client.remove_network(network_id)

    return jsonify({})


@app.route('/NetworkDriver.DeleteEndpoint', methods=['POST'])
def delete_endpoint():
    json_data = request.get_json(force=True)
    app.logger.debug("DeleteEndpoint JSON=%s", json_data)
    endpoint_id = json_data["EndpointID"]
    app.logger.info("Removing endpoint %s", endpoint_id)

    client.remove_endpoint(Endpoint(hostname, ORCHESTRATOR_ID, CONTAINER_NAME,
                                    endpoint_id, None, None))

    app.logger.debug("DeleteEndpoint response JSON=%s", "{}")
    return jsonify({})


@app.route('/NetworkDriver.Leave', methods=['POST'])
def leave():
    json_data = request.get_json(force=True)
    app.logger.debug("Leave JSON=%s", json_data)
    ep_id = json_data["EndpointID"]
    app.logger.info("Leaving endpoint %s", ep_id)

    remove_veth(generate_cali_interface_name(IF_PREFIX, ep_id))

    app.logger.debug("Leave response JSON=%s", "{}")
    return jsonify({})


@app.route('/NetworkDriver.DiscoverNew', methods=['POST'])
def discover_new():
    json_data = request.get_json(force=True)
    app.logger.debug("DiscoverNew JSON=%s", json_data)
    app.logger.debug("DiscoverNew response JSON=%s", "{}")
    return jsonify({})


@app.route('/NetworkDriver.DiscoverDelete', methods=['POST'])
def discover_delete():
    json_data = request.get_json(force=True)
    app.logger.debug("DiscoverNew JSON=%s", json_data)
    app.logger.debug("DiscoverDelete response JSON=%s", "{}")
    return jsonify({})


def remove_veth(name):
    """
    Best effort removal of veth, logging if removal fails.
    :param name: The name of the veth to remove
    """
    try:
        netns.remove_veth(name)
    except CalledProcessError:
        app.logger.warn("Failed to delete veth %s", name)
