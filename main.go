package main

import (
	"os"

	"github.com/docker/go-plugins-helpers/ipam"
	"github.com/docker/go-plugins-helpers/network"
	"github.com/projectcalico/libcalico-go/lib/apiconfig"
	"github.com/projectcalico/libcalico-go/lib/clientv3"
	"github.com/projectcalico/libnetwork-plugin/driver"
	log "github.com/sirupsen/logrus"

	"flag"

	"fmt"
)

const (
	ipamPluginName    = "calico-ipam"
	networkPluginName = "calico"
)

var (
	config *apiconfig.CalicoAPIConfig
	client clientv3.Interface
)

func init() {
	// Output to stderr instead of stdout, could also be a file.
	log.SetOutput(os.Stderr)
}

func initializeClient() {
	var err error

	if config, err = apiconfig.LoadClientConfig(""); err != nil {
		panic(err)
	}
	if client, err = clientv3.New(*config); err != nil {
		panic(err)
	}

	if os.Getenv("CALICO_DEBUG") != "" {
		log.SetLevel(log.DebugLevel)
		log.Debugln("Debug logging enabled")
	}
}

// VERSION is filled out during the build process (using git describe output)
var VERSION string

const (
	// The root user group id is 0
	ROOT_GID = 0
)

func main() {
	// Display the version on "-v"
	// Use a new flag set so as not to conflict with existing libraries which use "flag"
	flagSet := flag.NewFlagSet("Calico", flag.ExitOnError)

	version := flagSet.Bool("v", false, "Display version")
	err := flagSet.Parse(os.Args[1:])
	if err != nil {
		log.Fatalln(err)
	}
	if *version {
		fmt.Println(VERSION)
		os.Exit(0)
	}

	initializeClient()

	errChannel := make(chan error)
	networkHandler := network.NewHandler(driver.NewNetworkDriver(client))
	ipamHandler := ipam.NewHandler(driver.NewIpamDriver(client))

	go func(c chan error) {
		log.Infoln("calico-net has started.")
		err := networkHandler.ServeUnix(networkPluginName, ROOT_GID)
		log.Infoln("calico-net has stopped working.")
		c <- err
	}(errChannel)

	go func(c chan error) {
		log.Infoln("calico-ipam has started.")
		err := ipamHandler.ServeUnix(ipamPluginName, ROOT_GID)
		log.Infoln("calico-ipam has stopped working.")
		c <- err
	}(errChannel)

	err = <-errChannel

	log.Fatalln(err)
}
