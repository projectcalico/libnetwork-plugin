package test

import (
	"context"
	"fmt"
	"math/rand"
	"os"
	"os/exec"
	"strings"
	"time"

	etcdclient "github.com/coreos/etcd/client"
	"github.com/docker/docker/api/types/network"
	dockerclient "github.com/docker/docker/client"
	. "github.com/onsi/ginkgo"
	. "github.com/onsi/gomega/gexec"
)

var kapi etcdclient.KeysAPI

func init() {
	// Create a random seed
	rand.Seed(time.Now().UTC().UnixNano())

	cfg := etcdclient.Config{Endpoints: []string{"http://127.0.0.1:2379"}}
	c, _ := etcdclient.New(cfg)
	kapi = etcdclient.NewKeysAPI(c)
}

// GetDockerEndpoint gets the endpoint information from Docker
func GetDockerEndpoint(container, network string) *network.EndpointSettings {
	os.Setenv("DOCKER_API_VERSION", "1.24")
	os.Setenv("DOCKER_HOST", "http://localhost:5375")
	defer os.Setenv("DOCKER_HOST", "")
	cli, err := dockerclient.NewEnvClient()
	if err != nil {
		panic(err)
	}

	info, err := cli.ContainerInspect(context.Background(), container)
	if err != nil {
		panic(err)
	}

	return info.NetworkSettings.Networks[network]
}

// GetEtcdString gets a string for a given etcd path
func GetEtcdString(path string) string {
	// TODO - would be better to use libcalico to get data rather than talking to etcd direct
	resp, err := kapi.Get(context.Background(),
		path, nil)
	if err != nil {
		panic(err)
	}
	return resp.Node.Value
}

// CreatePool creates a pool in etcd
func CreatePool(pool string, ipv6 bool) {
	var ipv string
	if ipv6 {
		ipv = "v6"
	} else {
		ipv = "v4"
	}
	_, err := kapi.Set(context.Background(),
		fmt.Sprintf("/calico/v1/ipam/%s/pool/%s", ipv, strings.Replace(pool, "/", "-", -1)),
		fmt.Sprintf(`{"cidr": "%s"}`, pool), nil)
	if err != nil {
		panic(err)
	}
}

// WipeEtcd deletes everything under /calico from etcd
func WipeEtcd() {
	_, err := kapi.Delete(context.Background(), "/calico", &etcdclient.DeleteOptions{Dir: true, Recursive: true})
	if err != nil && !etcdclient.IsKeyNotFound(err) {
		panic(err)
	}
}

// DockerString runs a command on the  Docker in Docker host returning a string
func DockerString(cmd string) string {
	GinkgoWriter.Write([]byte(fmt.Sprintf("Running command [%s]\n", cmd)))
	command := exec.Command("bash", "-c", fmt.Sprintf("docker exec -i dind sh -c '%s'", cmd))
	_, _ = command.StdinPipe()
	out, err := command.Output()
	if err != nil {
		GinkgoWriter.Write(out)
		GinkgoWriter.Write(err.(*exec.ExitError).Stderr)
		Fail("Command failed")
	}
	return strings.TrimSpace(string(out))
}

// DockerSession runs a docker command returning the Session
func DockerSession(cmd string) *Session {
	GinkgoWriter.Write([]byte(fmt.Sprintf("Running command [%s]\n", cmd)))
	command := exec.Command("bash", "-c", fmt.Sprintf("docker exec -i dind sh -c '%s'", cmd))
	_, _ = command.StdinPipe()
	session, err := Start(command, GinkgoWriter, GinkgoWriter)
	if err != nil {
		Fail("Command failed")
	}
	return session
}

// RunPlugin uses "make" to run the plugin in a DIND container
func RunPlugin(additional_args string) {
	cmd := exec.Command("make", "run-plugin", fmt.Sprintf("ADDITIONAL_DIND_ARGS=%s", additional_args))
	cmd.Dir = "../../"
	output, err := cmd.Output()
	if err != nil {
		// On failure, print the stdout and stderr, then bail out
		fmt.Println(string(output))
		fmt.Println(string(err.(*exec.ExitError).Stderr))
		panic(err)
	}

	// Make sure the plugin has started by running a command against it.
	// This command should fail (we don't actually want to create a network).
	_, _ = exec.Command("bash", "-c", fmt.Sprintf("docker exec -i dind sh -c 'docker network create willfail -d calico'")).Output()
}
