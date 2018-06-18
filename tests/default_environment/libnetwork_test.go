package default_environment

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"os"
	"regexp"
	"time"

	. "github.com/onsi/ginkgo"
	. "github.com/onsi/gomega"
	. "github.com/onsi/gomega/gbytes"
	. "github.com/onsi/gomega/gexec"
	api "github.com/projectcalico/libcalico-go/lib/apis/v3"
	mathutils "github.com/projectcalico/libnetwork-plugin/utils/math"
	. "github.com/projectcalico/libnetwork-plugin/utils/test"
)

var _ = Describe("Libnetwork Tests", func() {
	BeforeEach(func() {
		WipeEtcd()
		CreatePool("poolv4", "192.169.0.0/16")
		CreatePool("poolv6", "2001:db8::/32")
	})

	// Run the plugin just once for all tests in this file.
	RunPlugin("")

	// Test the docker network commands - no need to test inspect or ls
	Describe("docker network create", func() {
		// TODO There is no coverage of the following two options. I can't see how to make them get passed to the plugin.
		// --label value
		// --aux-address
		Context("checking failure cases", func() {
			It("needs both network and IPAM drivers to be calico", func() {
				session := DockerSession("docker network create $RANDOM -d calico")
				Eventually(session).Should(Exit(1))
				Eventually(session.Err).Should(Say("Error response from daemon: NetworkDriver.CreateNetwork: Non-Calico IPAM driver is used"))
			})
			It("doesn't allow a gateway to be specified", func() {
				session := DockerSession("docker network create $RANDOM -d calico --ipam-driver calico-ipam --subnet=192.169.0.0/16 --gateway 192.169.0.1")
				Eventually(session).Should(Exit(1))
				expectedError := regexp.QuoteMeta("Error response from daemon: failed to allocate gateway (192.169.0.1): IpamDriver.RequestAddress: Calico IPAM does not support specifying a gateway.")
				Eventually(session.Err).Should(Say(expectedError))
			})
			It("requires the subnet to match the calico pool", func() {
				// I'm trying for a /24 but calico is configured with a /16 so it will fail.
				session := DockerSession("docker network create $RANDOM -d calico --ipam-driver calico-ipam --subnet=192.169.0.0/24")
				Eventually(session).Should(Exit(1))
				Eventually(session.Err).Should(Say("Error response from daemon: IpamDriver.RequestPool: The requested subnet must match the CIDR of a configured Calico IP Pool."))
			})
			It("rejects --internal being used", func() {
				session := DockerSession("docker network create $RANDOM --internal -d calico --ipam-driver calico-ipam")
				Eventually(session).Should(Exit(1))
				Eventually(session.Err).Should(Say("Error response from daemon: NetworkDriver.CreateNetwork: Calico driver does not support the flag --internal."))
			})
			It("rejects --ip-range being used", func() {
				session := DockerSession("docker network create $RANDOM --ip-range 192.169.1.0/24 --subnet=192.169.0.0/16 -d calico --ipam-driver calico-ipam")
				Eventually(session).Should(Exit(1))
				Eventually(session.Err).Should(Say("Error response from daemon: IpamDriver.RequestPool: Calico IPAM does not support sub pool configuration on 'docker create network'. Calico IP Pools should be configured first and IP assignment is from those pre-configured pools."))
			})
			It("rejects --ipam-opt being used", func() {
				session := DockerSession("docker network create $RANDOM --ipam-opt REJECT -d calico --ipam-driver calico-ipam")
				Eventually(session).Should(Exit(1))
				Eventually(session.Err).Should(Say("Error response from daemon: IpamDriver.RequestPool: Arbitrary options are not supported"))
			})
			It("rejects --opt being used", func() {
				session := DockerSession("docker network create $RANDOM --opt REJECT -d calico --ipam-driver calico-ipam")
				Eventually(session).Should(Exit(1))
				Eventually(session.Err).Should(Say("NetworkDriver.CreateNetwork: Calico driver does not support the flag REJECT."))
			})
			It("rejects multiple --opt being used", func() {
				session := DockerSession("docker network create $RANDOM --opt REJECT --opt REJECT2 -d calico --ipam-driver calico-ipam")
				Eventually(session).Should(Exit(1))
				Eventually(session.Err).Should(Say("NetworkDriver.CreateNetwork: Calico driver does not support the flags REJECT, REJECT2."))
			})
		})
		Context("checking success cases", func() {
			It("creates a network", func() {
				session := DockerSession("docker network create success$RANDOM -d calico --ipam-driver calico-ipam")
				Eventually(session).Should(Exit(0))
				// There are no observable side effects. We could verify that nothing changed under /calico in etcd?
				// I would like to verify that the correct pools were returned to Docker but it doesn't let us observe that information - https://github.com/docker/docker/issues/28567
			})
			It("creates a network with a subnet", func() {
				session := DockerSession("docker network create success$RANDOM --subnet 192.169.0.0/16 -d calico --ipam-driver calico-ipam")
				Eventually(session).Should(Exit(0))
			})
			It("creates a network with IPv6", func() {
				session := DockerSession("docker network create --ipv6 success$RANDOM -d calico --ipam-driver calico-ipam")
				Eventually(session).Should(Exit(0))
			})
			PIt("creates a network with IPv6 from a specific subnet", func() {
			})

			//TODO - allow multiple networks from the same pool
		})
	})
	Describe("docker network rm", func() {
		// No options and no side effects
	})
	Describe("docker network connect", func() {
		// TODO
		// Usage:	docker network connect [OPTIONS] NETWORK CONTAINER
		//
		//Connect a container to a network
		//
		//Options:
		//      --alias value           Add network-scoped alias for the container (default [])
		//      --help                  Print usage
		//      --ip string             IP Address
		//      --ip6 string            IPv6 Address
		//      --link value            Add link to another container (default [])
		//      --link-local-ip value   Add a link-local address for the container (default [])
		//
	})
	Describe("docker network disconnect", func() {
		// TODO - no significant options but we should observe the veth going and the endpoint removed from etcd
	})

	//docker create/run
	// create - doesn't have any network interactions until the container is started
	// run - Run a container, check the following
	//		- etcd contains correct info
	//		- host namespace contains the right veth with the right info
	//    - container - container the right routes and interface
	//	run can have the following variations -
	//    --mac-address
	//    --link-local-ip
	//    --ip and --ip6
	Describe("docker run", func() {
		var name string
		var pool string

		BeforeEach(func() {
			name = fmt.Sprintf("run%d", rand.Uint32())
			pool = fmt.Sprintf("testp%d", rand.Uint32())
			subnet := "192.170.0.0/16"
			CreatePool(pool, subnet)
			nid := DockerString(fmt.Sprintf("docker network create --driver calico --ipam-driver calico-ipam --subnet %s %s ", subnet, pool))
			UpdatePool(pool, subnet, nid)
		})

		AfterEach(func() {
			DockerString(fmt.Sprintf("docker rm -f %s", name))
			DockerString(fmt.Sprintf("docker network rm %s", pool))
		})

		It("creates a container on a network and checks all assertions", func() {
			// Create a container that will just sit in the background
			DockerString(fmt.Sprintf("docker run --net %s -tid --name %s %s", pool, name, os.Getenv("BUSYBOX_IMAGE")))

			// Gather information for assertions
			dockerEndpoint := GetDockerEndpoint(name, pool)
			ip := dockerEndpoint.IPAddress
			mac := dockerEndpoint.MacAddress
			endpointID := dockerEndpoint.EndpointID
			vethName := "cali" + endpointID[:mathutils.MinInt(11, len(endpointID))]

			// Check that the endpoint is created in etcd
			key := fmt.Sprintf("/calico/resources/v3/projectcalico.org/workloadendpoints/libnetwork/test-libnetwork-libnetwork-%s", endpointID)
			endpointJSON := GetEtcd(key)
			wep := api.NewWorkloadEndpoint()
			json.Unmarshal(endpointJSON, &wep)
			Expect(wep.Spec.InterfaceName).Should(Equal(vethName))

			// Check profile
			profile := api.NewProfile()
			json.Unmarshal(GetEtcd(fmt.Sprintf("/calico/resources/v3/projectcalico.org/profiles/%s", pool)), &profile)
			Expect(profile.Name).Should(Equal(pool))
			Expect(len(profile.Labels)).Should(Equal(0))
			//tags deprecated
			Expect(profile.Spec.Ingress[0].Action).Should(Equal(api.Allow))
			Expect(profile.Spec.Egress[0].Action).Should(Equal(api.Allow))

			// Check the interface exists on the Host - it has an autoassigned
			// mac and ip, so don't check anything!
			DockerString(fmt.Sprintf("ip addr show %s", vethName))

			// Make sure the interface in the container exists and has the  assigned ip and mac
			containerNICString := DockerString(fmt.Sprintf("docker exec -i %s ip addr", name))
			Expect(containerNICString).Should(ContainSubstring(ip))
			Expect(containerNICString).Should(ContainSubstring(mac))

			// Make sure the container has the routes we expect
			routes := DockerString(fmt.Sprintf("docker exec -i %s ip route", name))
			Expect(routes).Should(Equal("default via 169.254.1.1 dev cali0 \n169.254.1.1 dev cali0 scope link"))
		})

		It("creates a container with specific MAC", func() {
			// Create a container that will just sit in the background
			chosen_mac := "00:22:33:44:55:66"
			DockerString(fmt.Sprintf("docker run --mac-address %s --net %s -tid --name %s %s", chosen_mac, pool, name, os.Getenv("BUSYBOX_IMAGE")))

			// Gather information for assertions
			dockerEndpoint := GetDockerEndpoint(name, pool)
			ip := dockerEndpoint.IPAddress
			mac := dockerEndpoint.MacAddress
			endpointID := dockerEndpoint.EndpointID
			vethName := "cali" + endpointID[:mathutils.MinInt(11, len(endpointID))]

			// Make sure the discovered MAC is what we asked for
			Expect(mac).Should(Equal(chosen_mac))

			// Check that the endpoint is created in etcd
			key := fmt.Sprintf("/calico/resources/v3/projectcalico.org/workloadendpoints/libnetwork/test-libnetwork-libnetwork-%s", endpointID)
			endpointJSON := GetEtcd(key)
			wep := api.NewWorkloadEndpoint()
			json.Unmarshal(endpointJSON, &wep)
			Expect(wep.Spec.InterfaceName).Should(Equal(vethName))

			// Check the interface exists on the Host - it has an autoassigned
			// mac and ip, so don't check anything!
			DockerString(fmt.Sprintf("ip addr show %s", vethName))

			// Make sure the interface in the container exists and has the  assigned ip and mac
			containerNICString := DockerString(fmt.Sprintf("docker exec -i %s ip addr", name))
			Expect(containerNICString).Should(ContainSubstring(ip))
			Expect(containerNICString).Should(ContainSubstring(mac))

			// Make sure the container has the routes we expect
			routes := DockerString(fmt.Sprintf("docker exec -i %s ip route", name))
			Expect(routes).Should(Equal("default via 169.254.1.1 dev cali0 \n169.254.1.1 dev cali0 scope link"))
		})

		PIt("creates a container with specific link local address", func() { // https://github.com/docker/docker/issues/28606
			// Create a container that will just sit in the background
			DockerString(fmt.Sprintf("docker run --link-local-ip 169.254.0.50 --net %s -tid --name %s %s", pool, name, os.Getenv("BUSYBOX_IMAGE")))

			// Delete container
			DockerString(fmt.Sprintf("docker rm -f %s", name))
		})

		// TODO Ensure that  a specific IP isn't possible without a user specified subnet
		// TODO allocate specific IPs from specific pools - see test cases in https://github.com/projectcalico/libnetwork-plugin/pull/101/files/c8c0386a41a569fbef33fae545ad97fa061470ed#diff-3bca4eb4bf01d8f50e7babc5c90236cc
		// TODO auto alloc IPs from a specific pool - see https://github.com/projectcalico/libnetwork-plugin/pull/101/files/c8c0386a41a569fbef33fae545ad97fa061470ed#diff-2667baf0dbc5ac5027aa29690f306535
		It("creates a container with specific IP", func() {
			// Create a container that will just sit in the background
			chosen_ip := "192.170.50.51"
			DockerString(fmt.Sprintf("docker run --ip %s --net %s -tid --name %s %s", chosen_ip, pool, name, os.Getenv("BUSYBOX_IMAGE")))

			// Gather information for assertions
			dockerEndpoint := GetDockerEndpoint(name, pool)
			ip := dockerEndpoint.IPAddress
			mac := dockerEndpoint.MacAddress
			endpointID := dockerEndpoint.EndpointID
			vethName := "cali" + endpointID[:mathutils.MinInt(11, len(endpointID))]

			Expect(ip).Should(Equal(chosen_ip))

			// Check that the endpoint is created in etcd
			key := fmt.Sprintf("/calico/resources/v3/projectcalico.org/workloadendpoints/libnetwork/test-libnetwork-libnetwork-%s", endpointID)
			endpointJSON := GetEtcd(key)
			wep := api.NewWorkloadEndpoint()
			json.Unmarshal(endpointJSON, &wep)
			Expect(wep.Spec.InterfaceName).Should(Equal(vethName))

			// Check the interface exists on the Host - it has an autoassigned
			// mac and ip, so don't check anything!
			DockerString(fmt.Sprintf("ip addr show %s", vethName))

			// Make sure the interface in the container exists and has the  assigned ip and mac
			containerNICString := DockerString(fmt.Sprintf("docker exec -i %s ip addr", name))
			Expect(containerNICString).Should(ContainSubstring(ip))
			Expect(containerNICString).Should(ContainSubstring(mac))

			// Make sure the container has the routes we expect
			routes := DockerString(fmt.Sprintf("docker exec -i %s ip route", name))
			Expect(routes).Should(Equal("default via 169.254.1.1 dev cali0 \n169.254.1.1 dev cali0 scope link"))
		})

		It("creates a container with labels, but do not expect those in endpoint", func() {
			// Create a container that will just sit in the background
			DockerString(fmt.Sprintf("docker run --net %s -tid --label not=expected --label org.projectcalico.label.foo=bar --label org.projectcalico.label.baz=quux --name %s %s", pool, name, os.Getenv("BUSYBOX_IMAGE")))

			// Gather information for assertions
			dockerEndpoint := GetDockerEndpoint(name, pool)
			endpointID := dockerEndpoint.EndpointID
			vethName := "cali" + endpointID[:mathutils.MinInt(11, len(endpointID))]

			// Sleep to allow the plugin to query the started container and update the WEP
			// Alternative: query etcd until we hit jackpot or timeout
			time.Sleep(time.Second)

			// Check that the endpoint is created in etcd
			key := fmt.Sprintf("/calico/resources/v3/projectcalico.org/workloadendpoints/libnetwork/test-libnetwork-libnetwork-%s", endpointID)
			endpointJSON := GetEtcd(key)
			wep := api.NewWorkloadEndpoint()
			json.Unmarshal(endpointJSON, &wep)
			Expect(wep.Spec.InterfaceName).Should(Equal(vethName))
			_, ok := wep.ObjectMeta.Labels["foo"]
			Expect(ok).Should(Equal(false))
			_, ok = wep.ObjectMeta.Labels["baz"]
			Expect(ok).Should(Equal(false))
			_, ok = wep.ObjectMeta.Labels["not"]
			Expect(ok).Should(Equal(false))
		})
	})

	Describe("docker run ipv6", func() {
		var name string
		var pool string

		BeforeEach(func() {
			name = fmt.Sprintf("run%d", rand.Uint32())
			pool = fmt.Sprintf("test6p%d", rand.Uint32())
			subnet := "fdb7:472d:ff0b::/48"
			CreatePool(pool, subnet)
			nid := DockerString(fmt.Sprintf("docker network create --driver calico --ipam-driver calico-ipam --subnet %s --ipv6 %s ", subnet, pool))
			UpdatePool(pool, subnet, nid)
		})

		AfterEach(func() {
			DockerString(fmt.Sprintf("docker rm -f %s", name))
			DockerString(fmt.Sprintf("docker network rm %s", pool))
		})

		It("creates a container on a network and checks all assertions", func() {
			// Create a container that will just sit in the background
			DockerString(fmt.Sprintf("docker run --net %s -tid --name %s %s", pool, name, os.Getenv("BUSYBOX_IMAGE")))

			// Gather information for assertions
			dockerEndpoint := GetDockerEndpoint(name, pool)
			ipv6 := dockerEndpoint.GlobalIPv6Address
			mac := dockerEndpoint.MacAddress
			endpointID := dockerEndpoint.EndpointID
			vethName := "cali" + endpointID[:mathutils.MinInt(11, len(endpointID))]

			// Check that the endpoint is created in etcd
			key := fmt.Sprintf("/calico/resources/v3/projectcalico.org/workloadendpoints/libnetwork/test-libnetwork-libnetwork-%s", endpointID)
			endpointJSON := GetEtcd(key)
			wep := api.NewWorkloadEndpoint()
			json.Unmarshal(endpointJSON, &wep)
			Expect(wep.Spec.InterfaceName).Should(Equal(vethName))

			// Check the interface exists on the Host - it has an autoassigned
			// mac and ip, so don't check anything!
			DockerString(fmt.Sprintf("ip addr show %s", vethName))
			DockerString(fmt.Sprintf("ip -6 addr show %s", vethName))

			// Make sure the interface in the container exists and has the  assigned ip and mac
			containerNICString := DockerString(fmt.Sprintf("docker exec -i %s ip addr", name))
			Expect(containerNICString).Should(ContainSubstring(ipv6))
			Expect(containerNICString).Should(ContainSubstring(mac))

			// Make sure the container has the routes we expect
			routes := DockerString(fmt.Sprintf("docker exec -i %s ip route", name))
			Expect(routes).Should(Equal("default via 169.254.1.1 dev cali0 \n169.254.1.1 dev cali0 scope link"))
			routes6 := DockerString(fmt.Sprintf("docker exec -i %s ip -6 route", name))
			Expect(routes6).Should(MatchRegexp("default via fe80::.* dev cali0  metric 1024"))

		})
	})
	//docker stop/rm - stop and rm are the same as far as the plugin is concerned
	// TODO - check that the endpoint is removed from etcd and that the  veth is removed
})
