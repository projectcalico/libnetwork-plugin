package custom_wep_labelling

// Tests in this suite are for when the plugin has been configured to label
// workload endpoints

import (
	. "github.com/onsi/ginkgo"
	. "github.com/onsi/gomega"

	"testing"
)

func TestLibnetwork(t *testing.T) {
	RegisterFailHandler(Fail)
	RunSpecs(t, "Custom WEP labelling Libnetwork Suite")
}
