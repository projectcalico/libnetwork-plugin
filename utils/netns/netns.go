package netns

import (
	"net"

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

	err := netlink.LinkSetUp(veth)
	return err
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
