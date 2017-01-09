package driver

import (
	"log"
	"os"
)

const (
	// Calico IPAM module does not allow selection of pools from which to allocate
	// IP addresses.  The pool ID, which has to be supplied in the libnetwork IPAM
	// API is therefore fixed.  We use different values for IPv4 and IPv6 so that
	// during allocation we know which IP version to use.
	PoolIDV4 = "CalicoPoolIPv4"
	PoolIDV6 = "CalicoPoolIPv6"

	CalicoLocalAddressSpace  = "CalicoLocalAddressSpace"
	CalicoGlobalAddressSpace = "CalicoGlobalAddressSpace"
)

var IFPrefix = "cali"

func init() {
	if os.Getenv("CALICO_LIBNETWORK_IFPREFIX") != "" {
		IFPrefix = os.Getenv("CALICO_LIBNETWORK_IFPREFIX")
		log.Println("Updated CALICO_LIBNETWORK_IFPREFIX to ", IFPrefix)
	}
}
