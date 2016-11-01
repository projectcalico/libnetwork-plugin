package driver

import (
	"context"
	"log"
	"net"

	"github.com/pkg/errors"
	libcalicoErrors "github.com/projectcalico/libcalico-go/lib/errors"

	"github.com/docker/go-plugins-helpers/network"

	dockerClient "github.com/docker/engine-api/client"
	"github.com/projectcalico/libcalico-go/lib/api"
	datastoreClient "github.com/projectcalico/libcalico-go/lib/client"
	caliconet "github.com/projectcalico/libcalico-go/lib/net"

	logutils "github.com/projectcalico/libnetwork-plugin/utils/log"
	mathutils "github.com/projectcalico/libnetwork-plugin/utils/math"
	"github.com/projectcalico/libnetwork-plugin/utils/netns"
	osutils "github.com/projectcalico/libnetwork-plugin/utils/os"
)

// NetworkDriver is the Calico network driver representation.
// Must be used with Calico IPAM and support IPv4 only.
type NetworkDriver struct {
	client *datastoreClient.Client
	logger *log.Logger

	containerName  string
	orchestratorID string
	fixedMac       string

	gatewayCIDRV4 string
	gatewayCIDRV6 string

	ifPrefix string

	DummyIPV4Nexthop string
}

func NewNetworkDriver(client *datastoreClient.Client, logger *log.Logger) network.Driver {
	return NetworkDriver{
		client: client,
		logger: logger,

		// The MAC address of the interface in the container is arbitrary, so for
		// simplicity, use a fixed MAC.
		fixedMac: "EE:EE:EE:EE:EE:EE",

		// Orchestrator and container IDs used in our endpoint identification. These
		// are fixed for libnetwork.  Unique endpoint identification is provided by
		// hostname and endpoint ID.
		containerName:  "libnetwork",
		orchestratorID: "libnetwork",

		ifPrefix:         IFPrefix,
		DummyIPV4Nexthop: "169.254.1.1",
	}
}

func (d NetworkDriver) GetCapabilities() (*network.CapabilitiesResponse, error) {
	resp := network.CapabilitiesResponse{Scope: "global"}
	logutils.JSONMessage(d.logger, "GetCapabilities response JSON=%v", resp)
	return &resp, nil
}

func (d NetworkDriver) CreateNetwork(request *network.CreateNetworkRequest) error {
	logutils.JSONMessage(d.logger, "CreateNetwork JSON=%s", request)

	for _, ipData := range request.IPv4Data {
		if ipData.AddressSpace != CalicoGlobalAddressSpace {
			err := errors.New("Non-Calico IPAM driver is used")
			d.logger.Println(err)
			return err
		}
	}

	logutils.JSONMessage(d.logger, "CreateNetwork response JSON=%v", map[string]string{})
	return nil
}

func (d NetworkDriver) DeleteNetwork(request *network.DeleteNetworkRequest) error {
	logutils.JSONMessage(d.logger, "DeleteNetwork JSON=%v", request)
	return nil
}

func (d NetworkDriver) CreateEndpoint(request *network.CreateEndpointRequest) (*network.CreateEndpointResponse, error) {
	logutils.JSONMessage(d.logger, "CreateEndpoint JSON=%v", request)

	hostname, err := osutils.GetHostname()
	if err != nil {
		err = errors.Wrap(err, "Hostname fetching error")
		return nil, err
	}

	d.logger.Printf("Creating endpoint %v\n", request.EndpointID)
	if request.Interface.Address == "" {
		return nil, errors.New("No address assigned for endpoint")
	}

	var addresses []caliconet.IPNet
	if request.Interface.Address != "" {
		// Parse the address this function was passed. Ignore the subnet - Calico always uses /32 (for IPv4)
		ip4, _, err := net.ParseCIDR(request.Interface.Address)
		d.logger.Printf("Parsed IP %v from (%v) \n", ip4, request.Interface.Address)

		if err != nil {
			err = errors.Wrapf(err, "Parsing %v as CIDR failed", request.Interface.Address)
			d.logger.Println(err)
			return nil, err
		}

		addresses = append(addresses, caliconet.IPNet{IPNet: net.IPNet{IP: ip4, Mask: net.CIDRMask(32, 32)}})
	}

	endpoint := api.NewWorkloadEndpoint()
	endpoint.Metadata.Node = hostname
	endpoint.Metadata.Orchestrator = d.orchestratorID
	endpoint.Metadata.Workload = d.containerName
	endpoint.Metadata.Name = request.EndpointID
	endpoint.Spec.InterfaceName = "cali" + request.EndpointID[:mathutils.MinInt(11, len(request.EndpointID))]
	mac, _ := net.ParseMAC(d.fixedMac)
	endpoint.Spec.MAC = caliconet.MAC{HardwareAddr: mac}
	endpoint.Spec.IPNetworks = append(endpoint.Spec.IPNetworks, addresses...)

	// Use the Docker API to fetch the network name (so we don't have to use an ID everywhere)
	dockerCli, err := dockerClient.NewEnvClient()
	if err != nil {
		err = errors.Wrap(err, "Error while attempting to instantiate docker client from env")
		return nil, err
	}
	networkData, err := dockerCli.NetworkInspect(context.Background(), request.NetworkID)
	if err != nil {
		err = errors.Wrapf(err, "Network %v inspection error", request.NetworkID)
		return nil, err
	}

	// Now that we know the network name, set it on the endpoint.
	endpoint.Spec.Profiles = append(endpoint.Spec.Profiles, networkData.Name)

	// If a profile for the network name doesn't exist then it needs to be created.
	// We always attempt to create the profile and rely on the datastore to reject
	// the request if the profile already exists.
	profile := &api.Profile{
		Metadata: api.ProfileMetadata{Name: networkData.Name},
		Spec: api.ProfileSpec{
			Tags: []string{networkData.Name},
			EgressRules: []api.Rule{{Action: "allow"}},
			IngressRules: []api.Rule{{Action: "allow", Source: api.EntityRule{Tag: networkData.Name}}},
		},
	}
	if _, err := d.client.Profiles().Create(profile); err != nil {
		if _, ok := err.(libcalicoErrors.ErrorResourceAlreadyExists); !ok {
			log.Println(err)
			return nil, err
		}
	}

	// Create the endpoint
	_, err = d.client.WorkloadEndpoints().Create(endpoint)
	if err != nil {
		err = errors.Wrapf(err, "Workload endpoints creation error, data: %+v", endpoint)
		d.logger.Println(err)
		return nil, err
	}

	d.logger.Printf("Workload created, data: %+v\n", endpoint)

	response := &network.CreateEndpointResponse{
		Interface: &network.EndpointInterface{
			MacAddress: string(d.fixedMac),
		},
	}

	logutils.JSONMessage(d.logger, "CreateEndpoint response JSON=%v", response)

	return response, nil
}

func (d NetworkDriver) DeleteEndpoint(request *network.DeleteEndpointRequest) error {
	logutils.JSONMessage(d.logger, "DeleteEndpoint JSON=%v", request)
	hostname, err := osutils.GetHostname()
	if err != nil {
		err = errors.Wrap(err, "Hostname fetching error")
		return err
	}

	logutils.JSONMessage(d.logger, "DeleteEndpoint JSON=%v", request)
	d.logger.Printf("Removing endpoint %v\n", request.EndpointID)

	if err = d.client.WorkloadEndpoints().Delete(
		api.WorkloadEndpointMetadata{
			Name:         request.EndpointID,
			Node:         hostname,
			Orchestrator: d.orchestratorID,
			Workload:     d.containerName}); err != nil {
		err = errors.Wrapf(err, "Endpoint %v removal error", request.EndpointID)
		log.Println(err)
		return err
	}

	logutils.JSONMessage(d.logger, "DeleteEndpoint response JSON=%v", map[string]string{})

	return err
}

func (d NetworkDriver) EndpointInfo(request *network.InfoRequest) (*network.InfoResponse, error) {
	logutils.JSONMessage(d.logger, "EndpointInfo JSON=%v", request)
	return nil, nil
}

func (d NetworkDriver) Join(request *network.JoinRequest) (*network.JoinResponse, error) {
	logutils.JSONMessage(d.logger, "Join JSON=%v", request)

	// 1) Set up a veth pair
	// 	The one end will stay in the host network namespace - named caliXXXXX
	//	The other end is given a temporary name. It's moved into the final network namespace by libnetwork itself.
	var err error
	prefix := request.EndpointID[:mathutils.MinInt(11, len(request.EndpointID))]
	hostInterfaceName := "cali" + prefix
	tempInterfaceName := "temp" + prefix

	if err = netns.CreateVeth(hostInterfaceName, tempInterfaceName); err != nil {
		err = errors.Wrapf(
			err, "Veth creation error, hostInterfaceName=%v, tempInterfaceName=%v",
			hostInterfaceName, tempInterfaceName)
		d.logger.Println(err)
		return nil, err
	}

	// libnetwork doesn't set the MAC address properly, so set it here.
	if err = netns.SetVethMac(tempInterfaceName, d.fixedMac); err != nil {
		d.logger.Printf("Veth mac setting for %v failed, removing veth for %v\n", tempInterfaceName, hostInterfaceName)
		err = netns.RemoveVeth(hostInterfaceName)
		err = errors.Wrapf(err, "Veth removing for %v error", hostInterfaceName)
		d.logger.Println(err)
		return nil, err
	}

	resp := &network.JoinResponse{
		InterfaceName: network.InterfaceName{
			SrcName:   tempInterfaceName,
			DstPrefix: IFPrefix,
		},
	}

	// One of the network gateway addresses indicate that we are using
	// Calico IPAM driver.  In this case we setup routes using the gateways
	// configured on the endpoint (which will be our host IPs).
	d.logger.Println("Using Calico IPAM driver, configure gateway and " +
		"static routes to the host")

	resp.Gateway = d.DummyIPV4Nexthop
	resp.StaticRoutes = append(resp.StaticRoutes, &network.StaticRoute{
		Destination: d.DummyIPV4Nexthop + "/32",
		RouteType:   1, // 1 = CONNECTED
		NextHop:     "",
	})

	logutils.JSONMessage(d.logger, "Join Response JSON=%v", resp)

	return resp, nil
}

func (d NetworkDriver) Leave(request *network.LeaveRequest) error {
	logutils.JSONMessage(d.logger, "Leave response JSON=%v", request)
	caliName := "cali" + request.EndpointID[:mathutils.MinInt(11, len(request.EndpointID))]
	err := netns.RemoveVeth(caliName)
	return err
}

func (d NetworkDriver) DiscoverNew(request *network.DiscoveryNotification) error {
	logutils.JSONMessage(d.logger, "DiscoverNew JSON=%v", request)
	d.logger.Println("DiscoverNew response JSON={}")
	return nil
}

func (d NetworkDriver) DiscoverDelete(request *network.DiscoveryNotification) error {
	logutils.JSONMessage(d.logger, "DiscoverNew JSON=%v", request)
	d.logger.Println("DiscoverDelete response JSON={}")
	return nil
}

func (d NetworkDriver) ProgramExternalConnectivity(*network.ProgramExternalConnectivityRequest) error {
	return nil
}

func (d NetworkDriver) RevokeExternalConnectivity(*network.RevokeExternalConnectivityRequest) error {
	return nil
}
