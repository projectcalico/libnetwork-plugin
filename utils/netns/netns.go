package netns

import (
	"fmt"
	"net"
	"syscall"

	log "github.com/Sirupsen/logrus"

	"github.com/pkg/errors"
	"github.com/vishvananda/netlink"
)

func CreateVeth(vethNameHost, vethNameNSTemp string) error {
	veth := &netlink.Veth{
		LinkAttrs: netlink.LinkAttrs{
			Name: vethNameHost,
		},
		PeerName: vethNameNSTemp,
	}
	if err := netlink.LinkAdd(veth); err != nil {
		return err
	}
	vethTemp := &netlink.Veth{
		LinkAttrs: netlink.LinkAttrs{
			Name: vethNameNSTemp,
		},
		PeerName: vethNameHost,
	}
	// Set link state to up for both host and temp,
	if err := netlink.LinkSetUp(vethTemp); err != nil {
		return err
	}
	return netlink.LinkSetUp(veth)
}

func SetVethMac(vethNameHost, mac string) error {
	addr, err := net.ParseMAC(mac)
	if err != nil {
		return errors.Wrap(err, "Veth setting error")
	}
	return netlink.LinkSetHardwareAddr(&netlink.Veth{
		LinkAttrs: netlink.LinkAttrs{
			Name: vethNameHost,
		},
	}, addr)
}

func RemoveVeth(vethNameHost string) error {
	if ok, err := IsVethExists(vethNameHost); err != nil {
		return errors.Wrap(err, "Veth removal error")
	} else if !ok {
		return nil
	}
	return netlink.LinkDel(&netlink.Veth{
		LinkAttrs: netlink.LinkAttrs{
			Name: vethNameHost,
		},
	})
}

func IsVethExists(vethHostName string) (bool, error) {
	links, err := netlink.LinkList()
	if err != nil {
		return false, errors.Wrap(err, "Veth existing check error")
	}
	for _, link := range links {
		if link.Attrs().Name == vethHostName {
			return true, nil
		}
	}
	return false, nil
}

// GetLinkLocalAddr Get the IPv6 link local address of interfaceName
func GetLinkLocalAddr(interfaceName string) net.IP {
	link, err := netlink.LinkByName(interfaceName)
	if err != nil {
		log.Fatal(err)
	}
	addrs, err := netlink.AddrList(link, netlink.FAMILY_V6)
	if err != nil {
		log.Fatal(err)
	}
	var linkLocalAddr net.IP
	for _, addr := range addrs {
		if addr.Scope == syscall.RT_SCOPE_LINK {
			linkLocalAddr = addr.IP
			break
		}
	}
	if linkLocalAddr == nil {
		log.Warn(fmt.Sprintf("No IPv6 link local address found for interface: %s", interfaceName))
	}
	return linkLocalAddr
}
