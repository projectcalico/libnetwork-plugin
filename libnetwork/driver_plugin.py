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
import logging
import sys
import re

from pycalico.util import generate_cali_interface_name, IPV6_RE
from subprocess32 import CalledProcessError, check_output
from werkzeug.exceptions import HTTPException, default_exceptions
from netaddr import IPAddress, IPNetwork
from pycalico.block import AlreadyAssignedError
from pycalico.datastore_datatypes import IF_PREFIX, Endpoint, IPPool
from pycalico.datastore_errors import PoolNotFound
from pycalico import netns
from pycalico.util import get_hostname, get_ipv6_link_local

from datastore_libnetwork import LibnetworkDatastoreClient


# TODO: Move to libcalico constants
DUMMY_IPV4_NEXTHOP = "169.254.1.1"


# The MAC address of the interface in the container is arbitrary, so for
# simplicity, use a fixed MAC.
FIXED_MAC = "EE:EE:EE:EE:EE:EE"

# Orchestrator and container IDs used in our endpoint identification. These
# are fixed for libnetwork.  Unique endpoint identification is provided by
# hostname and endpoint ID.
CONTAINER_NAME = "libnetwork"
ORCHESTRATOR_ID = "libnetwork"

# Calico IPAM module does not allow selection of pools from which to allocate
# IP addresses.  The pool ID, which has to be supplied in the libnetwork IPAM
# API is therefore fixed.  We use different values for IPv4 and IPv6 so that
# during allocation we know which IP version to use.
POOL_ID_V4 = "CalicoPoolIPv4"
POOL_ID_V6 = "CalicoPoolIPv6"

# Fix pool and gateway CIDRs.  As per comment above, Calico IPAM does not allow
# assignment from a specific pool, so we choose a dummy value that will not be
# used in practise.  A 0/0 value is used for both IPv4 and IPv6.  This value is
# also used by the Network Driver to indicate that the Calico IPAM driver was
# used rather than the default libnetwork IPAM driver - this is useful because
# Calico Network Driver behavior depends on whether our IPAM driver was used or
# not.
POOL_CIDR_STR_V4 = "0.0.0.0/0"
POOL_CIDR_STR_V6 = "::/0"
GATEWAY_CIDR_STR_V4 = "0.0.0.0/0"
GATEWAY_CIDR_STR_V6 = "::/0"

# Calico-IPAM gateway CIDRs as an IPNetwork object
GATEWAY_NETWORK_V4 = IPNetwork(GATEWAY_CIDR_STR_V4)
GATEWAY_NETWORK_V6 = IPNetwork(GATEWAY_CIDR_STR_V6)

# How long to wait (seconds) for IP commands to complete.
IP_CMD_TIMEOUT = 5

# Initialise our hostname and datastore client.
hostname = get_hostname()
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
        wrapped_app.errorhandler(code)(make_json_error)

    return wrapped_app

app = make_json_app(__name__)
app.logger.addHandler(logging.StreamHandler(sys.stdout))
app.logger.setLevel(logging.DEBUG)
app.logger.info("Application started")

# The API calls below are documented at
# https://github.com/docker/libnetwork/blob/master/docs/remote.md

# <-- Plugin activation, we activate both libnetwork and ipam plugins -->

@app.route('/Plugin.Activate', methods=['POST'])
def activate():
    json_response = {"Implements": ["NetworkDriver", "IpamDriver"]}
    app.logger.debug("Activate response JSON=%s", json_response)
    return jsonify(json_response)

# <-- IPAM plugin API -->

@app.route('/IpamDriver.GetDefaultAddressSpaces', methods=['POST'])
def get_default_address_spaces():
    # Return fixed local and global address spaces.  The Calico IPAM module
    # does not use the address space when assigning IP addresses.  Instead
    # we assign from the pre-defined Calico IP pools.
    json_response = {
        "LocalDefaultAddressSpace": "CalicoLocalAddressSpace",
        "GlobalDefaultAddressSpace": "CalicoGlobalAddressSpace"
    }
    app.logger.debug("GetDefaultAddressSpace response JSON=%s", json_response)
    return jsonify(json_response)


@app.route('/IpamDriver.RequestPool', methods=['POST'])
def request_pool():
    # force is required since the request doesn't have the correct mimetype
    # If the JSON is malformed, then a BadRequest exception is raised,
    # which returns a HTTP 400 response.
    json_data = request.get_json(force=True)
    app.logger.debug("RequestPool JSON=%s", json_data)
    pool = json_data["Pool"]
    sub_pool = json_data.get("SubPool")
    v6 = json_data["V6"]

    # Calico IPAM does not allow you to request SubPool.
    if sub_pool:
        error_message = "Calico IPAM does not support sub pool configuration" \
                        "on 'docker create network'.  Calico IP Pools " \
                        "should be configured first and IP assignment is " \
                        "from those pre-configured pools."
        app.logger.error(error_message)
        raise Exception(error_message)

    # If a pool (subnet on the CLI) is specified, it must match one of the
    # preconfigured Calico pools.
    if pool:
        if not get_pool(IPNetwork(pool)):
            error_message = "The requested subnet must match the CIDR of a " \
                            "configured Calico IP Pool."
            app.logger.error(error_message)
            raise Exception(error_message)

    # If a subnet has been specified we use that as the pool ID. Otherwise, we
    # use static pool ID and CIDR to indicate that we are assigning from all of
    # the pools.
    if v6:
        pool_id = pool or POOL_ID_V6
        pool_cidr = POOL_CIDR_STR_V6
        gateway_cidr = GATEWAY_CIDR_STR_V6
    else:
        pool_id = pool or POOL_ID_V4
        pool_cidr = POOL_CIDR_STR_V4
        gateway_cidr = GATEWAY_CIDR_STR_V4

    # The meta data includes a dummy gateway address.  This prevents libnetwork
    # from requesting a gateway address from the pool since for a Calico
    # network our gateway is set to our host IP.
    json_response = {
        "PoolID": pool_id,
        "Pool": pool_cidr,
        "Data": {
            "com.docker.network.gateway": gateway_cidr
        }
    }
    app.logger.debug("RequestPool response JSON=%s", json_response)
    return jsonify(json_response)


@app.route('/IpamDriver.ReleasePool', methods=['POST'])
def release_pool():
    json_data = request.get_json(force=True)
    app.logger.debug("ReleasePool JSON=%s", json_data)
    pool_id = json_data["PoolID"]
    json_response = {}
    app.logger.debug("ReleasePool response JSON=%s", json_response)
    return jsonify(json_response)


@app.route('/IpamDriver.RequestAddress', methods=['POST'])
def request_address():
    json_data = request.get_json(force=True)
    app.logger.debug("RequestAddress JSON=%s", json_data)
    pool_id = json_data["PoolID"]
    address = json_data["Address"]

    if not address:
        app.logger.debug("Auto assigning IP from Calico pools")

        # No address requested, so auto assign from our pools.  If the pool ID
        # is one of the fixed IDs then assign from across all configured pools,
        # otherwise assign from the requested pool
        if pool_id == POOL_ID_V4:
            version = 4
            pool = None
        elif pool_id == POOL_ID_V6:
            version = 6
            pool = None
        else:
            pool_cidr = IPNetwork(pool_id)
            pool = get_pool(pool_cidr)
            if not pool:
                error_message = "The network references a Calico pool which " \
                                "has been deleted.  Please re-instate the " \
                                "Calico pool before using the network."
                app.logger.error(error_message)
                raise Exception(error_message)
            version = pool_cidr.version

        if version == 4:
            num_v4 = 1
            num_v6 = 0
            pool_v4 = pool
            pool_v6 = None
        else:
            num_v4 = 0
            num_v6 = 1
            pool_v4 = None
            pool_v6 = pool

        # Auto assign an IP based on whether the IPv4 or IPv6 pool was selected.
        # We auto-assign from all available pools with affinity based on our
        # host.
        ips_v4, ips_v6 = client.auto_assign_ips(num_v4, num_v6, None, None,
                                                pool=(pool_v4, pool_v6),
                                                host=hostname)
        ips = ips_v4 + ips_v6
        if not ips:
            error_message = "There are no available IP addresses in the " \
                            "configured Calico IP pools"
            app.logger.error(error_message)
            raise Exception(error_message)
    else:
        app.logger.debug("Reserving a specific address in Calico pools")
        try:
            ip_address = IPAddress(address)
            client.assign_ip(ip_address, None, {}, host=hostname)
            ips = [ip_address]
        except AlreadyAssignedError:
            error_message = "The address %s is already in " \
                            "use" % str(ip_address)
            app.logger.error(error_message)
            raise Exception(error_message)
        except PoolNotFound:
            error_message = "The address %s is not in one of the configured " \
                            "Calico IP pools" % str(ip_address)
            app.logger.error(error_message)
            raise Exception(error_message)

    # We should only have one IP address assigned at this point.
    assert len(ips) == 1, "Unexpected number of assigned IP addresses"

    # Return the IP as a CIDR.
    json_response = {
        "Address": str(IPNetwork(ips[0])),
        "Data": {}
    }
    app.logger.debug("RequestAddress response JSON=%s", json_response)
    return jsonify(json_response)


@app.route('/IpamDriver.ReleaseAddress', methods=['POST'])
def release_address():
    json_data = request.get_json(force=True)
    app.logger.debug("ReleaseAddress JSON=%s", json_data)
    address = json_data["Address"]

    # Unassign the address.  This handles the address already being unassigned
    # in which case it is a no-op.  The release_ips call may raise a
    # RuntimeError if there are repeated clashing updates to the same IP block,
    # this is not an expected condition.
    client.release_ips({IPAddress(address)})

    json_response = {}
    app.logger.debug("ReleaseAddress response JSON=%s", json_response)
    return jsonify(json_response)

# <-- libnetwork plugin API -->

@app.route('/NetworkDriver.GetCapabilities', methods=['POST'])
def get_capabilities():
    json_response = {"Scope": "global"}
    app.logger.debug("GetCapabilities response JSON=%s", json_response)
    return jsonify(json_response)


@app.route('/NetworkDriver.CreateNetwork', methods=['POST'])
def create_network():
    json_data = request.get_json(force=True)
    app.logger.debug("CreateNetwork JSON=%s", json_data)

    # Create the CNM "network" as a Calico profile.
    network_id = json_data["NetworkID"]
    app.logger.info("Creating profile %s", network_id)
    client.create_profile(network_id)

    for version in (4, 6):
        # Extract the gateway and pool from the network data.  If this
        # indicates that Calico IPAM is not being used, then create a Calico
        # IP pool.
        gateway, pool = get_gateway_pool_from_network_data(json_data, version)

        # Skip over versions that have no gateway assigned.
        if gateway is None:
            continue

        # If we aren't using Calico IPAM then we need to ensure an IP pool
        # exists.  IPIP and Masquerade options can be included on the network
        # create as additional options.  Note that this IP Pool has ipam=False
        # to ensure it is not used in Calico IPAM assignment.
        if not is_using_calico_ipam(gateway):
            options = json_data["Options"]["com.docker.network.generic"]
            ipip = options.get("ipip")
            masquerade = options.get("nat-outgoing")
            client.add_ip_pool(pool.version,
                               IPPool(pool, ipip=ipip, masquerade=masquerade,
                                      ipam=False))

    # Store off the JSON passed in on this request. It's required in later
    # calls.
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
    assert address_ip4 or address_ip6, "No address assigned for endpoint"

    # Create a Calico endpoint object.
    ep = Endpoint(hostname, ORCHESTRATOR_ID, CONTAINER_NAME, endpoint_id,
                  "active", FIXED_MAC)
    ep.profile_ids.append(network_id)

    if address_ip4:
        ep.ipv4_nets.add(IPNetwork(address_ip4))

    if address_ip6:
        ep.ipv6_nets.add(IPNetwork(address_ip6))

    app.logger.debug("Saving Calico endpoint: %s", ep)
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
    network_id = json_data["NetworkID"]
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

    # Initialise our response data.
    json_response = {
        "InterfaceName": {
            "SrcName": temp_interface_name,
            "DstPrefix": IF_PREFIX,
        }
    }

    # Extract relevant data from the Network data.
    network_data = get_network_data(network_id)
    gateway_ip4, _ = get_gateway_pool_from_network_data(network_data, 4)
    gateway_ip6, _ = get_gateway_pool_from_network_data(network_data, 6)

    if (gateway_ip4 and is_using_calico_ipam(gateway_ip4)) or \
       (gateway_ip6 and is_using_calico_ipam(gateway_ip6)):
        # One of the network gateway addresses indicate that we are using
        # Calico IPAM driver.  In this case we setup routes using the gateways
        # configured on the endpoint (which will be our host IPs).
        app.logger.debug("Using Calico IPAM driver, configure gateway and "
                         "static routes to the host")
        static_routes = []
        if gateway_ip4:
            json_response["Gateway"] = DUMMY_IPV4_NEXTHOP
            static_routes.append({
                "Destination": DUMMY_IPV4_NEXTHOP + "/32",
                "RouteType": 1,  # 1 = CONNECTED
                "NextHop": ""
            })
        if gateway_ip6:
            # Here, we'll report the link local address of the host's cali interface to libnetwork
            # as our IPv6 gateway. IPv6 link local addresses are automatically assigned to interfaces
            # when they are brought up. Unfortunately, the container link must be up as well. So
            # bring it up now
            # TODO: create_veth should already bring up both links
            bring_up_interface(temp_interface_name)
            # Then extract the link local address that was just assigned to our host's interface
            next_hop_6 = get_ipv6_link_local(host_interface_name)
            json_response["GatewayIPv6"] = next_hop_6
            static_routes.append({
                "Destination": str(IPNetwork(next_hop_6)),
                "RouteType": 1,  # 1 = CONNECTED
                "NextHop": ""
            })
        json_response["StaticRoutes"] = static_routes
    else:
        # We are not using Calico IPAM driver, so configure blank gateways to
        # set up auto-gateway behavior.
        app.logger.debug("Not using Calico IPAM driver")
        json_response["Gateway"] = ""
        json_response["GatewayIPv6"] = ""

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

    # Remove the pools that were created for this network.
    network_data = get_network_data(network_id)
    for version in (4, 6):
        gateway_cidr, pool_cidr = \
            get_gateway_pool_from_network_data(network_data, version)
        if gateway_cidr and not is_using_calico_ipam(gateway_cidr):
            client.remove_ip_pool(version, pool_cidr)
            app.logger.info("Removed pool %s", pool_cidr)

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


def get_network_data(network_id):
    """
    Return the network data (i.e. the JSON data that is passed in on the
    CreateNetwork request), or raise an exception if the network does not
    exist.

    :param network_id: The network ID.
    :return: The network data.
    """
    network_data = client.get_network(network_id)
    if not network_data:
        error_message = "Network %s does not exist" % network_id
        app.logger.error(error_message)
        raise Exception(error_message)
    return network_data


def get_gateway_pool_from_network_data(network_data, version):
    """
    Extract the gateway and pool from the network data.
    :param network_data: The network data.
    :param version: The IP version (4 or 6)
    :return: Tuple of (string gateway_CIDR,
                       string pool_CIDR)
             or (None, None) if either are not set.
    """
    assert version in [4,6]

    ip_data = network_data.get("IPv%sData" % version)
    if not ip_data:
        # No IP data for this IP version, so skip.
        app.logger.info("No IPv%s data", version)
        return None, None

    if len(ip_data) > 1:
        error_message = "Unsupported: multiple Gateways defined for " \
                        "IPv%s" % version
        app.logger.error(error_message)
        raise Exception(error_message)

    gateway = ip_data[0].get('Gateway')
    pool = ip_data[0].get('Pool')

    if not gateway or not pool:
        return None, None

    return IPNetwork(gateway), IPNetwork(pool)


def is_using_calico_ipam(gateway_cidr):
    """
    Determine if the gateway CIDR indicates that we are using Calico IPAM
    driver for IP assignment.
    :param gateway: The gateway CIDR.  This should not be None.
    :return: True, if using Calico IPAM driver.
    """
    # A 0 gateway IP indicates Calico IPAM is being used.
    assert isinstance(gateway_cidr, IPNetwork)
    return gateway_cidr in (GATEWAY_NETWORK_V4, GATEWAY_NETWORK_V6)


def get_pool(pool_cidr):
    """
    Return the Calico IP Pool with the specified pool CIDR, or None if not
    present.
    :param pool_cidr:  The pool CIDR.
    :return:  IPPool - The Calico pool, or None if not configured.
    """
    pools = client.get_ip_pools(pool_cidr.version, ipam=True)
    for pool in pools:
        if pool.cidr == pool_cidr:
            return pool
    return None


def bring_up_interface(interface_name):
    """
    Bring up an interface.
    """
    check_output(['ip', 'link', 'set', interface_name, 'up'], timeout=IP_CMD_TIMEOUT)
