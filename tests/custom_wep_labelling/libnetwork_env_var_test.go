package custom_wep_labelling

import (
	"encoding/json"
	"fmt"
	"math/rand"
	"os"
	"time"

	. "github.com/onsi/ginkgo"
	. "github.com/onsi/gomega"
	api "github.com/projectcalico/libcalico-go/lib/apis/v3"
	mathutils "github.com/projectcalico/libnetwork-plugin/utils/math"
	. "github.com/projectcalico/libnetwork-plugin/utils/test"
)

var _ = Describe("Running plugin with custom ENV", func() {
	Describe("docker run", func() {
		It("creates a container on a network with WEP labelling enabled", func() {
			RunPlugin("-e CALICO_LIBNETWORK_LABEL_ENDPOINTS=true")

			pool := "test"
			subnet := "192.169.1.0/24"
			// Since running the plugin starts etcd, the pool needs to be created after.
			CreatePool(pool, subnet)

			name := fmt.Sprintf("run%d", rand.Uint32())
			nid := DockerString(fmt.Sprintf("docker network create -d calico --ipam-driver calico-ipam --subnet %s %s ", subnet, pool))
			UpdatePool(pool, subnet, nid)

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
			v, ok := wep.ObjectMeta.Labels["foo"]
			Expect(ok).Should(Equal(true))
			Expect(v).Should(Equal("bar"))
			v, ok = wep.ObjectMeta.Labels["baz"]
			Expect(ok).Should(Equal(true))
			Expect(v).Should(Equal("quux"))
			_, ok = wep.ObjectMeta.Labels["not"]
			Expect(ok).Should(Equal(false))

			// Check profile
			profile := api.NewProfile()
			json.Unmarshal(GetEtcd(fmt.Sprintf("/calico/resources/v3/projectcalico.org/profiles/%s", pool)), &profile)
			Expect(profile.Name).Should(Equal(pool))
			Expect(len(profile.Labels)).Should(Equal(0))
			//tags deprecated
			Expect(profile.Spec.Ingress[0].Action).Should(Equal(api.Allow))
			Expect(profile.Spec.Egress[0].Action).Should(Equal(api.Allow))

			// Delete container
			DockerString(fmt.Sprintf("docker rm -f %s", name))
		})
	})

	Describe("docker run", func() {
		It("creates a container on a network with WEP labelling enabled and profile creation disabled", func() {
			// Run the plugin with custom IFPREFIX
			RunPlugin("-e CALICO_LIBNETWORK_LABEL_ENDPOINTS=true -e CALICO_LIBNETWORK_CREATE_PROFILES=false")

			pool := "test2"
			subnet := "192.169.2.0/24"
			// Since running the plugin starts etcd, the pool needs to be created after.
			CreatePool(pool, subnet)

			name := fmt.Sprintf("run%d", rand.Uint32())
			nid := DockerString(fmt.Sprintf("docker network create -d calico --ipam-driver calico-ipam --subnet %s %s ", subnet, pool))
			UpdatePool(pool, subnet, nid)

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
			v, ok := wep.ObjectMeta.Labels["foo"]
			Expect(ok).Should(Equal(true))
			Expect(v).Should(Equal("bar"))
			v, ok = wep.ObjectMeta.Labels["baz"]
			Expect(ok).Should(Equal(true))
			Expect(v).Should(Equal("quux"))
			_, ok = wep.ObjectMeta.Labels["not"]
			Expect(ok).Should(Equal(false))

			// Chech profile not created
			notExists := GetNotExists(fmt.Sprintf("/calico/resources/v3/projectcalico.org/profiles/%s", pool))
			Expect(notExists).Should(BeTrue())

			// Check that the endpoint is created in etcd
			// Delete container
			DockerString(fmt.Sprintf("docker rm -f %s", name))
		})
	})
})
