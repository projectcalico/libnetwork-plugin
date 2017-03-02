package driver

import (
	"fmt"
	"net"

	log "github.com/Sirupsen/logrus"
	"github.com/pkg/errors"

	"github.com/docker/go-plugins-helpers/ipam"
	"github.com/projectcalico/libcalico-go/lib/api"
	datastoreClient "github.com/projectcalico/libcalico-go/lib/client"
	caliconet "github.com/projectcalico/libcalico-go/lib/net"
	logutils "github.com/projectcalico/libnetwork-plugin/utils/log"
	osutils "github.com/projectcalico/libnetwork-plugin/utils/os"
)

type IpamDriver struct {
	client *datastoreClient.Client

	poolIDV4 string
	poolIDV6 string
}

func NewIpamDriver(client *datastoreClient.Client) ipam.Ipam {
	return IpamDriver{
		client: client,

		poolIDV4: PoolIDV4,
		poolIDV6: PoolIDV6,
	}
}

func (i IpamDriver) GetCapabilities() (*ipam.CapabilitiesResponse, error) {
	resp := ipam.CapabilitiesResponse{}
	logutils.JSONMessage("GetCapabilities response", resp)
	return &resp, nil
}

func (i IpamDriver) GetDefaultAddressSpaces() (*ipam.AddressSpacesResponse, error) {
	resp := &ipam.AddressSpacesResponse{
		LocalDefaultAddressSpace:  CalicoLocalAddressSpace,
		GlobalDefaultAddressSpace: CalicoGlobalAddressSpace,
	}
	logutils.JSONMessage("GetDefaultAddressSpace response", resp)
	return resp, nil
}

func (i IpamDriver) RequestPool(request *ipam.RequestPoolRequest) (*ipam.RequestPoolResponse, error) {
	logutils.JSONMessage("RequestPool", request)

	// Calico IPAM does not allow you to request a SubPool.
	if request.SubPool != "" {
		err := errors.New(
			"Calico IPAM does not support sub pool configuration " +
				"on 'docker create network'. Calico IP Pools " +
				"should be configured first and IP assignment is " +
				"from those pre-configured pools.",
		)
		log.Errorln(err)
		return nil, err
	}

	if len(request.Options) != 0 {
		err := errors.New("Arbitrary options are not supported")
		log.Errorln(err)
		return nil, err
	}
	var poolID string
	var pool string
	var gateway string
	if request.V6 {
		// Default the poolID to the fixed value.
		poolID = i.poolIDV6
		pool = "::/0"
		gateway = "::/0"
	} else {
		// Default the poolID to the fixed value.
		poolID = i.poolIDV4
		pool = "0.0.0.0/0"
		gateway = "0.0.0.0/0"
	}

	// If a pool (subnet on the CLI) is specified, it must match one of the
	// preconfigured Calico pools.
	if request.Pool != "" {
		poolsClient := i.client.IPPools()
		_, ipNet, err := caliconet.ParseCIDR(request.Pool)
		if err != nil {
			err := errors.New("Invalid CIDR")
			log.Errorln(err)
			return nil, err
		}

		pools, err := poolsClient.List(api.IPPoolMetadata{CIDR: *ipNet})
		if err != nil || len(pools.Items) < 1 {
			err := errors.New("The requested subnet must match the CIDR of a " +
				"configured Calico IP Pool.",
			)
			log.Errorln(err)
			return nil, err
		}
		pool = request.Pool
		poolID = request.Pool
	}

	// We use static pool ID and CIDR. We don't need to signal the
	// The meta data includes a dummy gateway address. This prevents libnetwork
	// from requesting a gateway address from the pool since for a Calico
	// network our gateway is set to a special IP.
	resp := &ipam.RequestPoolResponse{
		PoolID: poolID,
		Pool:   pool,
		Data:   map[string]string{"com.docker.network.gateway": gateway},
	}

	logutils.JSONMessage("RequestPool response", resp)

	return resp, nil
}

func (i IpamDriver) ReleasePool(request *ipam.ReleasePoolRequest) error {
	logutils.JSONMessage("ReleasePool", request)
	return nil
}

func (i IpamDriver) RequestAddress(request *ipam.RequestAddressRequest) (*ipam.RequestAddressResponse, error) {
	logutils.JSONMessage("RequestAddress", request)

	hostname, err := osutils.GetHostname()
	if err != nil {
		log.Errorln(err)
		return nil, err
	}

	// Calico IPAM does not allow you to choose a gateway.
	if request.Options["RequestAddressType"] == "com.docker.network.gateway" {
		err := errors.New("Calico IPAM does not support specifying a gateway.")
		log.Errorln(err)
		return nil, err
	}

	var IPs []caliconet.IP

	if request.Address == "" {
		// No address requested, so auto assign from our pools.
		log.Println("Auto assigning IP from Calico pools")

		// If the poolID isn't the fixed one then find the pool to assign from.
		// poolV4 defaults to nil to assign from across all pools.
		var poolV4 []caliconet.IPNet

		var poolV6 []caliconet.IPNet
		var numIPv4, numIPv6, version int
		if request.PoolID == PoolIDV4 {
			version = 4
			numIPv4 = 1
			numIPv6 = 0
		} else if request.PoolID == PoolIDV6 {
			version = 6
			numIPv4 = 0
			numIPv6 = 1
		} else {
			poolsClient := i.client.IPPools()
			_, ipNet, err := caliconet.ParseCIDR(request.PoolID)
			if err != nil {
				err = errors.Wrapf(err, "Invalid CIDR - %v", request.PoolID)
				log.Errorln(err)
				return nil, err
			}
			pool, err := poolsClient.Get(api.IPPoolMetadata{CIDR: *ipNet})
			if err != nil {
				err := errors.New("The network references a Calico pool which " +
					"has been deleted. Please re-instate the " +
					"Calico pool before using the network.")
				log.Errorln(err)
				return nil, err
			}
			version = ipNet.Version()
			if version == 4 {
				poolV4 = []caliconet.IPNet{caliconet.IPNet{IPNet: pool.Metadata.CIDR.IPNet}}
				log.Debugln("Using specific pool ", poolV4)
			} else if version == 6 {
				poolV6 = []caliconet.IPNet{caliconet.IPNet{IPNet: pool.Metadata.CIDR.IPNet}}
				log.Debugln("Using specific pool ", poolV6)
			}
		}

		// Auto assign an IP address.
		// IPv4/v6 pool will be nil if the docker network doesn't have a subnet associated with.
		// Otherwise, it will be set to the Calico pool to assign from.
		IPsV4, IPsV6, err := i.client.IPAM().AutoAssign(
			datastoreClient.AutoAssignArgs{
				Num4:      numIPv4,
				Num6:      numIPv6,
				Hostname:  hostname,
				IPv4Pools: poolV4,
				IPv6Pools: poolV6,
			},
		)

		if err != nil {
			err = errors.Wrapf(err, "IP assignment error")
			log.Errorln(err)
			return nil, err
		}
		IPs = append(IPsV4, IPsV6...)
	} else {
		// Docker allows the users to specify any address.
		// We'll return an error if the address isn't in a Calico pool, but we don't care which pool it's in
		// (i.e. it doesn't need to match the subnet from the docker network).
		log.Debugln("Reserving a specific address in Calico pools")
		ip := net.ParseIP(request.Address)
		ipArgs := datastoreClient.AssignIPArgs{
			IP:       caliconet.IP{IP: ip},
			Hostname: hostname,
		}
		err := i.client.IPAM().AssignIP(ipArgs)
		if err != nil {
			err = errors.Wrapf(err, "IP assignment error, data: %+v", ipArgs)
			log.Errorln(err)
			return nil, err
		}
		IPs = []caliconet.IP{{IP: ip}}
	}

	// We should only have one IP address assigned at this point.
	if len(IPs) != 1 {
		err := errors.New(fmt.Sprintf("Unexpected number of assigned IP addresses. "+
			"A single address should be assigned. Got %v", IPs))
		log.Errorln(err)
		return nil, err
	}

	// Return the IP as a CIDR.
	var respAddr string
	if IPs[0].Version() == 4 {
		// IPv4 address
		respAddr = fmt.Sprintf("%v/%v", IPs[0], "32")
	} else {
		// IPv6 address
		respAddr = fmt.Sprintf("%v/%v", IPs[0], "128")
	}
	resp := &ipam.RequestAddressResponse{
		Address: respAddr,
	}

	logutils.JSONMessage("RequestAddress response", resp)

	return resp, nil
}

func (i IpamDriver) ReleaseAddress(request *ipam.ReleaseAddressRequest) error {
	logutils.JSONMessage("ReleaseAddress", request)

	ip := caliconet.IP{IP: net.ParseIP(request.Address)}

	// Unassign the address.  This handles the address already being unassigned
	// in which case it is a no-op.
	_, err := i.client.IPAM().ReleaseIPs([]caliconet.IP{ip})
	if err != nil {
		err = errors.Wrapf(err, "IP releasing error, ip: %v", ip)
		log.Errorln(err)
		return err
	}

	return nil
}
