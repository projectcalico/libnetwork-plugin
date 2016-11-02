package os

import "os"

const hostnameEnv = "HOSTNAME"

func GetHostname() (string, error) {
	hostnameFromEnv := os.Getenv(hostnameEnv)
	if hostname, err := os.Hostname(); hostnameFromEnv == "" {
		return hostname, err
	}
	return hostnameFromEnv, nil
}
