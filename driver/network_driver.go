package driver

import (
	"context"
	"fmt"
	"net"
	"os"
	"sort"
	"strings"
	"time"

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

const DOCKER_LABEL_PREFIX = "org.projectcalico.label."
const LABEL_POLL_TIMEOUT_ENVKEY = "CALICO_LIBNETWORK_LABEL_POLL_TIMEOUT"
const CREATE_PROFILES_ENVKEY = "CALICO_LIBNETWORK_CREATE_PROFILES"
const LABEL_ENDPOINTS_ENVKEY = "CALICO_LIBNETWORK_LABEL_ENDPOINTS"

// NetworkDriver is the Calico network driver representation.
// Must be used with Calico IPAM and supports IPv4 only.
type NetworkDriver struct {
	client         *datastoreClient.Client
	containerName  string
	orchestratorID string
	fixedMac       string

	ifPrefix string

	DummyIPV4Nexthop string

	labelPollTimeout time.Duration

	createProfiles bool
	labelEndpoints bool
}

func NewNetworkDriver(client *datastoreClient.Client) network.Driver {
	driver := NetworkDriver{
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

		// default: enabled, disable by setting env key to false (case insensitive)
		createProfiles: !strings.EqualFold(os.Getenv(CREATE_PROFILES_ENVKEY), "false"),

		// default: disabled, enable by setting env key to true (case insensitive)
		labelEndpoints: strings.EqualFold(os.Getenv(LABEL_ENDPOINTS_ENVKEY), "true"),
	}

	if !driver.createProfiles {
		log.Info("Feature disabled: no Calico profiles will be created per network")
	}
	if driver.labelEndpoints {
		log.Info("Feature enabled: Calico workloadendpoints will be labelled with Docker labels")
		driver.labelPollTimeout = getLabelPollTimeout()
	}
	return driver
}

func (d NetworkDriver) GetCapabilities() (*network.CapabilitiesResponse, error) {
	resp := network.CapabilitiesResponse{Scope: "global"}
	logutils.JSONMessage("GetCapabilities response", resp)
	return &resp, nil
}

// AllocateNetwork is used for swarm-mode support in remote plugins, which
// Calico's libnetwork-plugin doesn't currently support.
func (d NetworkDriver) AllocateNetwork(request *network.AllocateNetworkRequest) (*network.AllocateNetworkResponse, error) {
	var resp network.AllocateNetworkResponse
	logutils.JSONMessage("AllocateNetwork response", resp)
	return &resp, nil
}

// FreeNetwork is used for swarm-mode support in remote plugins, which
// Calico's libnetwork-plugin doesn't currently support.
func (d NetworkDriver) FreeNetwork(request *network.FreeNetworkRequest) error {
	logutils.JSONMessage("FreeNetwork request", request)
	return nil
}

func (d NetworkDriver) CreateNetwork(request *network.CreateNetworkRequest) error {
	logutils.JSONMessage("CreateNetwork", request)
	knownOpts := map[string]bool{"com.docker.network.enable_ipv6": true}
	// Reject all options (--internal, --enable_ipv6, etc)
	for k, v := range request.Options {
		skip := false
		for known, _ := range knownOpts {
			if k == known {
				skip = true
				break
			}
		}
		if skip {
			continue
		}
		optionSet := false
		flagName := k
		flagValue := fmt.Sprintf("%s", v)
		multipleFlags := false
		switch v := v.(type) {
		case bool:
			// if v == true then optionSet = true
			optionSet = v
			flagName = "--" + strings.TrimPrefix(k, "com.docker.network.")
			flagValue = ""
			break
		case map[string]interface{}:
			optionSet = len(v) != 0
			flagName = ""
			numFlags := 0
			// Sort flags for consistent error reporting
			flags := []string{}
			for flag := range v {
				flags = append(flags, flag)
			}
			sort.Strings(flags)

			for _, flag := range flags {
				flagName = flagName + flag + ", "
				numFlags++
			}
			multipleFlags = numFlags > 1
			flagName = strings.TrimSuffix(flagName, ", ")
			flagValue = ""
			break
		default:
			// for unknown case let optionSet = true
			optionSet = true
		}
		if optionSet {
			if flagValue != "" {
				flagValue = " (" + flagValue + ")"
			}
			f := "flag"
			if multipleFlags {
				f = "flags"
			}
			err := errors.New("Calico driver does not support the " + f + " " + flagName + flagValue + ".")
			log.Errorln(err)
			return err
		}
	}

	for _, ipData := range request.IPv4Data {
		// Older version of Docker have a bug where they don't provide the correct AddressSpace
		// so we can't check for calico IPAM using our known address space.
		// The Docker issue, https://github.com/projectcalico/libnetwork-plugin/issues/77,
		// was fixed sometime between 1.11.2 and 1.12.3.
		// Also the pool might not have a fixed values if --subnet was passed
		// So the only safe thing is to check for our special gateway value
		if ipData.Gateway != "0.0.0.0/0" {
			err := errors.New("Non-Calico IPAM driver is used. Note: Docker before 1.12.3 is unsupported")
			log.Errorln(err)
			return err
		}
	}

	for _, ipData := range request.IPv6Data {
		// Don't support older versions of Docker which have a bug where the correct AddressSpace isn't provided
		if ipData.AddressSpace != CalicoGlobalAddressSpace {
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
	if request.Interface.Address == "" && request.Interface.AddressIPv6 == "" {
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

	if request.Interface.AddressIPv6 != "" {
		// Parse the address this function was passed.
		ip6, ipnet, err := net.ParseCIDR(request.Interface.AddressIPv6)
		log.Debugf("Parsed IP %v from (%v) \n", ip6, request.Interface.AddressIPv6)
		if err != nil {
			err = errors.Wrapf(err, "Parsing %v as CIDR failed", request.Interface.AddressIPv6)
			log.Errorln(err)
			return nil, err
		}
		addresses = append(addresses, caliconet.IPNet{IPNet: *ipnet})
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

	if d.createProfiles {
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
	}

	// Create the endpoint last to minimize side-effects if something goes wrong.
	_, err = d.client.WorkloadEndpoints().Create(endpoint)
	if err != nil {
		err = errors.Wrapf(err, "Workload endpoints creation error, data: %+v", endpoint)
		log.Errorln(err)
		return nil, err
	}

	log.Debugf("Workload created, data: %+v\n", endpoint)

	if d.labelEndpoints {
		go d.populateWorkloadEndpointWithLabels(request.NetworkID, endpoint)
	}

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

	linkLocalAddr := netns.GetLinkLocalAddr(hostInterfaceName)
	if linkLocalAddr == nil {
		log.Warnf("No IPv6 link local address for %s", hostInterfaceName)
	} else {
		resp.GatewayIPv6 = fmt.Sprintf("%s", linkLocalAddr)
		nextHopIPv6 := fmt.Sprintf("%s/128", linkLocalAddr)
		resp.StaticRoutes = append(resp.StaticRoutes, &network.StaticRoute{
			Destination: nextHopIPv6,
			RouteType:   1, // 1 = CONNECTED
			NextHop:     "",
		})
	}

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
	logutils.JSONMessage("DiscoverDelete", request)
	log.Debugln("DiscoverDelete response JSON={}")
	return nil
}

func (d NetworkDriver) ProgramExternalConnectivity(*network.ProgramExternalConnectivityRequest) error {
	return nil
}

func (d NetworkDriver) RevokeExternalConnectivity(*network.RevokeExternalConnectivityRequest) error {
	return nil
}

// Try to get the container's labels and update the WorkloadEndpoint with them
// Since we do not get container info in the libnetwork API methods we need to
// get them ourselves.
//
// This is how:
// - first we try to get a list of containers attached to the custom network
// - if there is a container with our endpointID, we try to inspect that container
// - any labels for that container prefixed by our 'magic' prefix are added to
//   our WorkloadEndpoint resource
//
// Above may take 1 or more retries, because Docker has to update the
// container list in the NetworkInspect and make the Container available
// for inspecting.
func (d NetworkDriver) populateWorkloadEndpointWithLabels(networkID string, endpoint *api.WorkloadEndpoint) {
	endpointID := endpoint.Metadata.Name

	retrySleep := time.Duration(100 * time.Millisecond)

	start := time.Now()
	deadline := start.Add(d.labelPollTimeout)

	dockerCli, err := dockerClient.NewEnvClient()
	if err != nil {
		err = errors.Wrap(err, "Error while attempting to instantiate docker client from env")
		log.Errorln(err)
		return
	}
	defer dockerCli.Close()

RETRY_NETWORK_INSPECT:
	if time.Now().After(deadline) {
		log.Errorf("Getting labels for workloadEndpoint timed out in network inspect loop. Took %s", time.Since(start))
		return
	}

	// inspect our custom network
	networkData, err := dockerCli.NetworkInspect(context.Background(), networkID)
	if err != nil {
		err = errors.Wrapf(err, "Error inspecting network %s - retrying (T=%s)", networkID, time.Since(start))
		log.Warningln(err)
		// was unable to inspect network, let's retry
		time.Sleep(retrySleep)
		goto RETRY_NETWORK_INSPECT
	}
	logutils.JSONMessage("NetworkInspect response", networkData)

	// try to find the container for which we created an endpoint
	containerID := ""
	for id, containerInNetwork := range networkData.Containers {
		if containerInNetwork.EndpointID == endpointID {
			// skip funky identified containers - observed with dind 1.13.0-rc3, gone in -rc5
			// {
			//   "Containers": {
			//     "ep-736ccfa7cd61ced93b67f7465ddb79633ea6d1f718a8ca7d9d19226f5d3521b0": {
			//       "Name": "run1466946597",
			//       "EndpointID": "736ccfa7cd61ced93b67f7465ddb79633ea6d1f718a8ca7d9d19226f5d3521b0",
			//       ...
			//     }
			//   }
			// }
			if strings.HasPrefix(id, "ep-") {
				log.Debugf("Skipping container entry with matching endpointID, but illegal id: %s", id)
			} else {
				containerID = id
				log.Debugf("Container %s found in NetworkInspect result (T=%s)", containerID, time.Since(start))
				break
			}
		}
	}

	if containerID == "" {
		// cause: Docker has not yet processed the libnetwork CreateEndpoint response.
		log.Warnf("Container not found in NetworkInspect result - retrying (T=%s)", time.Since(start))
		// let's retry
		time.Sleep(retrySleep)
		goto RETRY_NETWORK_INSPECT
	}

RETRY_CONTAINER_INSPECT:
	if time.Now().After(deadline) {
		log.Errorf("Getting labels for workloadEndpoint timed out in container inspect loop. Took %s", time.Since(start))
		return
	}

	containerInfo, err := dockerCli.ContainerInspect(context.Background(), containerID)
	if err != nil {
		err = errors.Wrapf(err, "Error inspecting container %s for labels - retrying (T=%s)", containerID, time.Since(start))
		log.Warningln(err)
		// was unable to inspect container, let's retry
		time.Sleep(100 * time.Millisecond)
		goto RETRY_CONTAINER_INSPECT
	}

	log.Debugf("Container inspected, processing labels now (T=%s)", time.Since(start))

	// make sure we have a labels map in the workloadEndpoint
	if endpoint.Metadata.Labels == nil {
		endpoint.Metadata.Labels = map[string]string{}
	}

	labelsFound := 0
	for label, labelValue := range containerInfo.Config.Labels {
		if !strings.HasPrefix(label, DOCKER_LABEL_PREFIX) {
			continue
		}
		labelsFound++
		labelClean := strings.TrimPrefix(label, DOCKER_LABEL_PREFIX)
		endpoint.Metadata.Labels[labelClean] = labelValue
		log.Debugf("Found label for WorkloadEndpoint: %s=%s", labelClean, labelValue)
	}

	if labelsFound == 0 {
		log.Debugf("No labels found for container (T=%s)", endpointID, time.Since(start))
		return
	}

	// lets update the workloadEndpoint
	_, err = d.client.WorkloadEndpoints().Update(endpoint)
	if err != nil {
		err = errors.Wrapf(err, "Unable to update WorkloadEndpoint with labels (T=%s)", time.Since(start))
		log.Errorln(err)
		return
	}

	log.Infof("WorkloadEndpoint %s updated with labels: %v (T=%s)",
		endpointID, endpoint.Metadata.Labels, time.Since(start))

}

// Returns the label poll timeout. Default is returned unless an environment
// key is set to a valid time.Duration.
func getLabelPollTimeout() time.Duration {
	// 5 seconds should be more than enough for this plugin to get the
	// container labels. More info in func populateWorkloadEndpointWithLabels
	defaultTimeout := time.Duration(5 * time.Second)

	timeoutVal := os.Getenv(LABEL_POLL_TIMEOUT_ENVKEY)
	if timeoutVal == "" {
		return defaultTimeout
	}

	labelPollTimeout, err := time.ParseDuration(timeoutVal)
	if err != nil {
		err = errors.Wrapf(err, "Label poll timeout specified via env key %s is invalid, using default %s",
			LABEL_POLL_TIMEOUT_ENVKEY, defaultTimeout)
		log.Warningln(err)
		return defaultTimeout
	}
	log.Infof("Using custom label poll timeout: %s", labelPollTimeout)
	return labelPollTimeout
}
