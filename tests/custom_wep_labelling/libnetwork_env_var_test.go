package custom_wep_labelling

import (
	"fmt"
	"math/rand"
	"time"

	. "github.com/onsi/ginkgo"
	. "github.com/onsi/gomega"
	mathutils "github.com/projectcalico/libnetwork-plugin/utils/math"
	. "github.com/projectcalico/libnetwork-plugin/utils/test"
)

var _ = Describe("Running plugin with custom ENV", func() {
	Describe("docker run", func() {
		It("creates a container on a network with WEP labelling enabled", func() {
			RunPlugin("-e CALICO_LIBNETWORK_LABEL_ENDPOINTS=true")

			// Since running the plugin starts etcd, the pool needs to be created after.
			CreatePool("192.169.1.0/24", false)

			name := fmt.Sprintf("run%d", rand.Uint32())
			DockerString(fmt.Sprintf("docker network create %s -d calico --ipam-driver calico-ipam", name))

			// Create a container that will just sit in the background
			DockerString(fmt.Sprintf("docker run --net %s -tid --label not=expected --label org.projectcalico.label.foo=bar --label org.projectcalico.label.baz=quux --name %s busybox", name, name))

			// Gather information for assertions
			docker_endpoint := GetDockerEndpoint(name, name)
			ip := docker_endpoint.IPAddress
			mac := docker_endpoint.MacAddress
			endpoint_id := docker_endpoint.EndpointID
			interface_name := "cali" + endpoint_id[:mathutils.MinInt(11, len(endpoint_id))]

			// Sleep to allow the plugin to query the started container and update the WEP
			// Alternative: query etcd until we hit jackpot or timeout
			time.Sleep(time.Second)

			// Check that the endpoint is created in etcd
			etcd_endpoint := GetEtcdString(fmt.Sprintf("/calico/v1/host/test/workload/libnetwork/libnetwork/endpoint/%s", endpoint_id))
			Expect(etcd_endpoint).Should(MatchJSON(fmt.Sprintf(
				`{"state":"active","name":"%s","mac":"%s","profile_ids":["%s"],"ipv4_nets":["%s/32"],"ipv6_nets":[],"labels":{"baz":"quux","foo": "bar"}}`,
				interface_name, mac, name, ip)))

			// Check profile
			tags := GetEtcdString(fmt.Sprintf("/calico/v1/policy/profile/%s/tags", name))
			labels := GetEtcdString(fmt.Sprintf("/calico/v1/policy/profile/%s/labels", name))
			rules := GetEtcdString(fmt.Sprintf("/calico/v1/policy/profile/%s/rules", name))
			Expect(tags).Should(MatchJSON(fmt.Sprintf(`["%s"]`, name)))
			Expect(labels).Should(MatchJSON("{}"))
			Expect(rules).Should(MatchJSON(fmt.Sprintf(`{"inbound_rules": [{"action": "allow","src_tag": "%s"}],"outbound_rules":[{"action": "allow"}]}`, name)))

			// Delete container
			DockerString(fmt.Sprintf("docker rm -f %s", name))
		})
	})

	Describe("docker run", func() {
		It("creates a container on a network with WEP labelling enabled and profile creation disabled", func() {
			// Run the plugin with custom IFPREFIX
			RunPlugin("-e CALICO_LIBNETWORK_LABEL_ENDPOINTS=true -e CALICO_LIBNETWORK_CREATE_PROFILES=false")

			// Since running the plugin starts etcd, the pool needs to be created after.
			CreatePool("192.169.2.0/24", true)

			name := fmt.Sprintf("run%d", rand.Uint32())
			DockerString(fmt.Sprintf("docker network create %s -d calico --ipam-driver calico-ipam", name))

			// Create a container that will just sit in the background
			DockerString(fmt.Sprintf("docker run --net %s -tid --label not=expected --label org.projectcalico.label.foo=bar --label org.projectcalico.label.baz=quux --name %s busybox", name, name))

			// Gather information for assertions
			docker_endpoint := GetDockerEndpoint(name, name)
			ip := docker_endpoint.IPAddress
			mac := docker_endpoint.MacAddress
			endpoint_id := docker_endpoint.EndpointID
			interface_name := "cali" + endpoint_id[:mathutils.MinInt(11, len(endpoint_id))]

			// Sleep to allow the plugin to query the started container and update the WEP
			// Alternative: query etcd until we hit jackpot or timeout
			time.Sleep(time.Second)

			// Check that the endpoint is created in etcd
			etcd_endpoint := GetEtcdString(fmt.Sprintf("/calico/v1/host/test/workload/libnetwork/libnetwork/endpoint/%s", endpoint_id))
			Expect(etcd_endpoint).Should(MatchJSON(fmt.Sprintf(
				`{"state":"active","name":"%s","mac":"%s","profile_ids":null,"ipv4_nets":["%s/32"],"ipv6_nets":[],"labels":{"baz":"quux","foo": "bar"}}`,
				interface_name, mac, ip)))

			// Delete container
			DockerString(fmt.Sprintf("docker rm -f %s", name))
		})
	})

})
