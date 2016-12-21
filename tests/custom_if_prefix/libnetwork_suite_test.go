package custom_if_prefix

// Tests in this suite are for when the plugin has been run with a custom IF prefix

import (
	. "github.com/onsi/ginkgo"
	. "github.com/onsi/gomega"

	"testing"
)

func TestLibnetwork(t *testing.T) {
	RegisterFailHandler(Fail)
	RunSpecs(t, "Custom IF Prefix Libnetwork Suite")
}
