package default_environment

// Tests in this suite are for testing when the plugin without additinal
// environemnt variables

import (
	. "github.com/onsi/ginkgo"
	. "github.com/onsi/gomega"

	"testing"
)

func TestLibnetwork(t *testing.T) {
	RegisterFailHandler(Fail)
	RunSpecs(t, "Default Libnetwork Suite")
}
