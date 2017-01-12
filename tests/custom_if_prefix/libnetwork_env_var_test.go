package custom_if_prefix

import (
	"fmt"
	"math/rand"

	. "github.com/onsi/ginkgo"
	. "github.com/onsi/gomega"
	mathutils "github.com/projectcalico/libnetwork-plugin/utils/math"
	. "github.com/projectcalico/libnetwork-plugin/utils/test"
)

var _ = Describe("Running plugin with custom ENV", func() {
	Describe("docker run", func() {
		It("creates a container on a network with correct IFPREFIX", func() {
			// Run the plugin with custom IFPREFIX
			RunPlugin("-e CALICO_LIBNETWORK_IFPREFIX=test")

			// Since running the plugin starts etcd, the pool needs to be created after.
			CreatePool("192.169.0.0/16", false)

			name := fmt.Sprintf("run%d", rand.Uint32())
			DockerString(fmt.Sprintf("docker network create %s -d calico --ipam-driver calico-ipam", name))

			// Create a container that will just sit in the background
			DockerString(fmt.Sprintf("docker run --net %s -tid --name %s busybox", name, name))

			// Gather information for assertions
			docker_endpoint := GetDockerEndpoint(name, name)
			ip := docker_endpoint.IPAddress
			mac := docker_endpoint.MacAddress
			endpoint_id := docker_endpoint.EndpointID
			interface_name := "cali" + endpoint_id[:mathutils.MinInt(11, len(endpoint_id))]

			// Check that the endpoint is created in etcd
			etcd_endpoint := GetEtcdString(fmt.Sprintf("/calico/v1/host/test/workload/libnetwork/libnetwork/endpoint/%s", endpoint_id))
			Expect(etcd_endpoint).Should(MatchJSON(fmt.Sprintf(
				`{"state":"active","name":"%s","mac":"%s","profile_ids":["%s"],"ipv4_nets":["%s/32"],"ipv6_nets":[]}`,
				interface_name, mac, name, ip)))

			// Check profile
			tags := GetEtcdString(fmt.Sprintf("/calico/v1/policy/profile/%s/tags", name))
			labels := GetEtcdString(fmt.Sprintf("/calico/v1/policy/profile/%s/labels", name))
			rules := GetEtcdString(fmt.Sprintf("/calico/v1/policy/profile/%s/rules", name))
			Expect(tags).Should(MatchJSON(fmt.Sprintf(`["%s"]`, name)))
			Expect(labels).Should(MatchJSON("{}"))
			Expect(rules).Should(MatchJSON(fmt.Sprintf(`{"inbound_rules": [{"action": "allow","src_tag": "%s"}],"outbound_rules":[{"action": "allow"}]}`, name)))

			// Check the interface exists on the Host - it has an autoassigned
			// mac and ip, so don't check anything!
			DockerString(fmt.Sprintf("ip addr show %s", interface_name))

			// Make sure the interface in the container exists and has the  assigned ip and mac
			container_interface_string := DockerString(fmt.Sprintf("docker exec -i %s ip addr", name))
			Expect(container_interface_string).Should(ContainSubstring(ip))
			Expect(container_interface_string).Should(ContainSubstring(mac))

			// Make sure the container has the routes we expect
			routes := DockerString(fmt.Sprintf("docker exec -i %s ip route", name))
			Expect(routes).Should(Equal("default via 169.254.1.1 dev test0 \n169.254.1.1 dev test0"))

			// Delete container
			DockerString(fmt.Sprintf("docker rm -f %s", name))
		})
	})
})
