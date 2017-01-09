package driver

import (
	"context"
	"net"

	log "github.com/Sirupsen/logrus"
	"github.com/pkg/errors"
	libcalicoErrors "github.com/projectcalico/libcalico-go/lib/errors"

	dockerClient "github.com/docker/docker/client"
	"github.com/docker/go-plugins-helpers/network"
	"github.com/projectcalico/libcalico-go/lib/api"
	datastoreClient "github.com/projectcalico/libcalico-go/lib/client"
	caliconet "github.com/projectcalico/libcalico-go/lib/net"

	logutils "github.com/projectcalico/libnetwork-plugin/utils/log"
	mathutils "github.com/projectcalico/libnetwork-plugin/utils/math"
	"github.com/projectcalico/libnetwork-plugin/utils/netns"
	osutils "github.com/projectcalico/libnetwork-plugin/utils/os"
)

// NetworkDriver is the Calico network driver representation.
// Must be used with Calico IPAM and supports IPv4 only.
type NetworkDriver struct {
	client         *datastoreClient.Client
	containerName  string
	orchestratorID string
	fixedMac       string

	ifPrefix string

	DummyIPV4Nexthop string
}

func NewNetworkDriver(client *datastoreClient.Client) network.Driver {
	return NetworkDriver{
		client: client,

		// The MAC address of the interface in the container is arbitrary, for
		// simplicity, use a fixed MAC unless overridden by user.
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
	logutils.JSONMessage("GetCapabilities response", resp)
	return &resp, nil
}

func (d NetworkDriver) CreateNetwork(request *network.CreateNetworkRequest) error {
	logutils.JSONMessage("CreateNetwork", request)

	genericOpts, ok := request.Options["com.docker.network.generic"]
	if ok {
		opts, ok := genericOpts.(map[string]interface{})
		if ok && len(opts) != 0 {
			err := errors.New("Arbitrary options are not supported")
			log.Println(err)
			return err
		}
	}

	// Calico driver does not allow you use the --internal flag
	internal, ok := request.Options["com.docker.network.internal"].(bool)
	if ok && internal {
		err := errors.New("Calico driver does not support the --internal flag.")
		log.Errorln(err)
		return err
	}

	for _, ipData := range request.IPv4Data {
		// Older version of Docker have a bug where they don't provide the correct AddressSpace
		// so we can't check for calico IPAM using our known address space.
		// Also the pool might not have a fixed values if --subnet was passed
		// So the only safe thing is to check for our special gateway value
		if ipData.Gateway != "0.0.0.0/0" {
			err := errors.New("Non-Calico IPAM driver is used")
			log.Errorln(err)
			return err
		}
	}

	logutils.JSONMessage("CreateNetwork response", map[string]string{})
	return nil
}

func (d NetworkDriver) DeleteNetwork(request *network.DeleteNetworkRequest) error {
	logutils.JSONMessage("DeleteNetwork", request)
	return nil
}

func (d NetworkDriver) CreateEndpoint(request *network.CreateEndpointRequest) (*network.CreateEndpointResponse, error) {
	logutils.JSONMessage("CreateEndpoint", request)

	hostname, err := osutils.GetHostname()
	if err != nil {
		err = errors.Wrap(err, "Hostname fetching error")
		log.Errorln(err)
		return nil, err
	}

	log.Debugf("Creating endpoint %v\n", request.EndpointID)
	if request.Interface.Address == "" {
		err := errors.New("No address assigned for endpoint")
		log.Errorln(err)
		return nil, err
	}

	var addresses []caliconet.IPNet
	if request.Interface.Address != "" {
		// Parse the address this function was passed. Ignore the subnet - Calico always uses /32 (for IPv4)
		ip4, _, err := net.ParseCIDR(request.Interface.Address)
		log.Debugf("Parsed IP %v from (%v) \n", ip4, request.Interface.Address)

		if err != nil {
			err = errors.Wrapf(err, "Parsing %v as CIDR failed", request.Interface.Address)
			log.Errorln(err)
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
	userProvidedMac := (request.Interface.MacAddress != "")
	var mac net.HardwareAddr
	if userProvidedMac {
		if mac, err = net.ParseMAC(request.Interface.MacAddress); err != nil {
			err = errors.Wrap(err, "Error parsing MAC address")
			log.Errorln(err)
			return nil, err
		}
	} else {
		mac, _ = net.ParseMAC(d.fixedMac)
	}
	endpoint.Spec.MAC = &caliconet.MAC{HardwareAddr: mac}
	endpoint.Spec.IPNetworks = append(endpoint.Spec.IPNetworks, addresses...)

	// Use the Docker API to fetch the network name (so we don't have to use an ID everywhere)
	dockerCli, err := dockerClient.NewEnvClient()
	if err != nil {
		err = errors.Wrap(err, "Error while attempting to instantiate docker client from env")
		log.Errorln(err)
		return nil, err
	}
	defer dockerCli.Close()
	networkData, err := dockerCli.NetworkInspect(context.Background(), request.NetworkID)
	if err != nil {
		err = errors.Wrapf(err, "Network %v inspection error", request.NetworkID)
		log.Errorln(err)
		return nil, err
	}

	// Now that we know the network name, set it on the endpoint.
	endpoint.Spec.Profiles = append(endpoint.Spec.Profiles, networkData.Name)

	// If a profile for the network name doesn't exist then it needs to be created.
	// We always attempt to create the profile and rely on the datastore to reject
	// the request if the profile already exists.
	profile := &api.Profile{
		Metadata: api.ProfileMetadata{
			Name: networkData.Name,
			Tags: []string{networkData.Name},
		},
		Spec: api.ProfileSpec{
			EgressRules:  []api.Rule{{Action: "allow"}},
			IngressRules: []api.Rule{{Action: "allow", Source: api.EntityRule{Tag: networkData.Name}}},
		},
	}
	if _, err := d.client.Profiles().Create(profile); err != nil {
		if _, ok := err.(libcalicoErrors.ErrorResourceAlreadyExists); !ok {
			log.Errorln(err)
			return nil, err
		}
	}

	// Create the endpoint last to minimize side-effects if something goes wrong.
	_, err = d.client.WorkloadEndpoints().Create(endpoint)
	if err != nil {
		err = errors.Wrapf(err, "Workload endpoints creation error, data: %+v", endpoint)
		log.Errorln(err)
		return nil, err
	}

	log.Debugf("Workload created, data: %+v\n", endpoint)
	var endpointInterface network.EndpointInterface
	if !userProvidedMac {
		endpointInterface = network.EndpointInterface{
			MacAddress: string(d.fixedMac),
		}
	} else {
		// empty string indicates user provided MAC address.
		endpointInterface = network.EndpointInterface{
			MacAddress: "",
		}
	}
	response := &network.CreateEndpointResponse{Interface: &endpointInterface}

	logutils.JSONMessage("CreateEndpoint response", response)

	return response, nil
}

func (d NetworkDriver) DeleteEndpoint(request *network.DeleteEndpointRequest) error {
	logutils.JSONMessage("DeleteEndpoint", request)
	log.Debugf("Removing endpoint %v\n", request.EndpointID)

	hostname, err := osutils.GetHostname()
	if err != nil {
		err = errors.Wrap(err, "Hostname fetching error")
		log.Errorln(err)
		return err
	}

	if err = d.client.WorkloadEndpoints().Delete(
		api.WorkloadEndpointMetadata{
			Name:         request.EndpointID,
			Node:         hostname,
			Orchestrator: d.orchestratorID,
			Workload:     d.containerName}); err != nil {
		err = errors.Wrapf(err, "Endpoint %v removal error", request.EndpointID)
		log.Errorln(err)
		return err
	}

	logutils.JSONMessage("DeleteEndpoint response JSON=%v", map[string]string{})

	return err
}

func (d NetworkDriver) EndpointInfo(request *network.InfoRequest) (*network.InfoResponse, error) {
	logutils.JSONMessage("EndpointInfo", request)
	return nil, nil
}

func (d NetworkDriver) Join(request *network.JoinRequest) (*network.JoinResponse, error) {
	logutils.JSONMessage("Join", request)

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
		log.Errorln(err)
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
	log.Debugln("Using Calico IPAM driver, configure gateway and static routes to the host")

	resp.Gateway = d.DummyIPV4Nexthop
	resp.StaticRoutes = append(resp.StaticRoutes, &network.StaticRoute{
		Destination: d.DummyIPV4Nexthop + "/32",
		RouteType:   1, // 1 = CONNECTED
		NextHop:     "",
	})

	logutils.JSONMessage("Join response", resp)

	return resp, nil
}

func (d NetworkDriver) Leave(request *network.LeaveRequest) error {
	logutils.JSONMessage("Leave response", request)
	caliName := "cali" + request.EndpointID[:mathutils.MinInt(11, len(request.EndpointID))]
	err := netns.RemoveVeth(caliName)
	return err
}

func (d NetworkDriver) DiscoverNew(request *network.DiscoveryNotification) error {
	logutils.JSONMessage("DiscoverNew", request)
	log.Debugln("DiscoverNew response JSON={}")
	return nil
}

func (d NetworkDriver) DiscoverDelete(request *network.DiscoveryNotification) error {
	logutils.JSONMessage("DiscoverNew", request)
	log.Debugln("DiscoverDelete response JSON={}")
	return nil
}

func (d NetworkDriver) ProgramExternalConnectivity(*network.ProgramExternalConnectivityRequest) error {
	return nil
}

func (d NetworkDriver) RevokeExternalConnectivity(*network.RevokeExternalConnectivityRequest) error {
	return nil
}
