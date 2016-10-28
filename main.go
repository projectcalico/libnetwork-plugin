package main

import (
	"log"

	"os"

	"github.com/docker/go-plugins-helpers/ipam"
	"github.com/docker/go-plugins-helpers/network"
	"github.com/projectcalico/libcalico-go/lib/api"
	"github.com/projectcalico/libnetwork-plugin/driver"

	datastoreClient "github.com/projectcalico/libcalico-go/lib/client"
	"flag"
	"fmt"
)

const (
	ipamPluginName    = "calico-ipam"
	networkPluginName = "calico"
)

var (
	config    *api.ClientConfig
	client    *datastoreClient.Client

	logger *log.Logger
)

func init() {
	var err error

	if config, err = datastoreClient.LoadClientConfig(""); err != nil {
		panic(err)
	}
	if client, err = datastoreClient.New(*config); err != nil {
		panic(err)
	}

	logger = log.New(os.Stdout, "", log.LstdFlags)
}

// VERSION is filled out during the build process (using git describe output)
var VERSION string

func main() {
	// Display the version on "-v"
	// Use a new flag set so as not to conflict with existing libraries which use "flag"
	flagSet := flag.NewFlagSet("Calico", flag.ExitOnError)

	version := flagSet.Bool("v", false, "Display version")
	err := flagSet.Parse(os.Args[1:])
	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
	if *version {
		fmt.Println(VERSION)
		os.Exit(0)
	}

	errChannel := make(chan error)
	networkHandler := network.NewHandler(driver.NewNetworkDriver(client, logger))
	ipamHandler := ipam.NewHandler(driver.NewIpamDriver(client, logger))

	go func(c chan error) {
		logger.Println("calico-net has started.")
		err := networkHandler.ServeUnix("root", networkPluginName)
		logger.Println("calico-net has stopped working.")
		c <- err
	}(errChannel)

	go func(c chan error) {
		logger.Println("calico-ipam has started.")
		err := ipamHandler.ServeUnix("root", ipamPluginName)
		logger.Println("calico-ipam has stopped working.")
		c <- err
	}(errChannel)

	err = <-errChannel

	log.Fatal(err)
}
