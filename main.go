package main

import (
	"log"

	"os"

	"github.com/Sirupsen/logrus"
	"github.com/docker/go-plugins-helpers/ipam"
	"github.com/docker/go-plugins-helpers/network"
	"github.com/projectcalico/libcalico-go/lib/api"
	"github.com/projectcalico/libnetwork-plugin/driver"

	"flag"

	datastoreClient "github.com/projectcalico/libcalico-go/lib/client"
)

const (
	ipamPluginName    = "calico-ipam"
	networkPluginName = "calico"
)

var (
	config *api.ClientConfig
	client *datastoreClient.Client

	logger *logrus.Logger
)

func init() {
	var err error

	if config, err = datastoreClient.LoadClientConfig(""); err != nil {
		panic(err)
	}
	if client, err = datastoreClient.New(*config); err != nil {
		panic(err)
	}

	logger = logrus.New()

	if os.Getenv("CALICO_DEBUG") != "" {
		logrus.SetLevel(logrus.DebugLevel)
	}
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
		logger.Fatalln(err)
	}
	if *version {
		logger.Infoln(VERSION)
		os.Exit(0)
	}

	errChannel := make(chan error)
	networkHandler := network.NewHandler(driver.NewNetworkDriver(client, logger))
	ipamHandler := ipam.NewHandler(driver.NewIpamDriver(client, logger))

	go func(c chan error) {
		logger.Infoln("calico-net has started.")
		err := networkHandler.ServeUnix("root", networkPluginName)
		logger.Infoln("calico-net has stopped working.")
		c <- err
	}(errChannel)

	go func(c chan error) {
		logger.Infoln("calico-ipam has started.")
		err := ipamHandler.ServeUnix("root", ipamPluginName)
		logger.Infoln("calico-ipam has stopped working.")
		c <- err
	}(errChannel)

	err = <-errChannel

	log.Fatalln(err)
}
