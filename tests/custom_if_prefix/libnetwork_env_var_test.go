package custom_if_prefix

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"os"

	. "github.com/onsi/ginkgo"
	. "github.com/onsi/gomega"
	api "github.com/projectcalico/libcalico-go/lib/apis/v3"
	mathutils "github.com/projectcalico/libnetwork-plugin/utils/math"
	. "github.com/projectcalico/libnetwork-plugin/utils/test"
)

var _ = Describe("Running plugin with custom ENV", func() {
	Describe("docker run", func() {
		It("creates a container on a network with correct IFPREFIX", func() {
			// Run the plugin with custom IFPREFIX
			RunPlugin("-e CALICO_LIBNETWORK_IFPREFIX=test")

			pool := "test"
			subnet := "192.169.0.0/16"
			// Since running the plugin starts etcd, the pool needs to be created after.
			CreatePool(pool, subnet)

			name := fmt.Sprintf("run%d", rand.Uint32())
			nid := DockerString(fmt.Sprintf("docker network create --driver calico --ipam-driver calico-ipam --subnet %s %s ", subnet, pool))
			UpdatePool(pool, subnet, nid)

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
			Expect(routes).Should(Equal("default via 169.254.1.1 dev test0 \n169.254.1.1 dev test0 scope link"))

			// Delete container
			DockerString(fmt.Sprintf("docker rm -f %s", name))
		})
	})
})
