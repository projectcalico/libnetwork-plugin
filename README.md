[![Build Status](https://semaphoreci.com/api/v1/projects/d51a0276-7939-409e-80ac-aa5df9421fef/510521/badge.svg)](https://semaphoreci.com/calico/libnetwork-plugin)
[![Circle CI](https://circleci.com/gh/projectcalico/libnetwork-plugin/tree/master.svg?style=svg)](https://circleci.com/gh/projectcalico/libnetwork-plugin/tree/master)

# Libnetwork plugin for Calico

This plugin for Docker networking ([libnetwork](https://github.com/docker/libnetwork)) is intended for use with [Project Calico](http://www.projectcalico.org).
The plugin is integrated with the `calico/node` image which is created from the [calico-containers](https://github.com/projectcalico/calico-containers) repository.

Guides on how to get started with the plugin and further documentation is available from http://docs.projectcalico.org

The remaining information is for advanced users. 

## How to Run It
`make run-plugin`

Running the plugin in a container requires a few specific options
 `docker run --rm --net=host --privileged -e CALICO_ETCD_AUTHORITY=$(LOCAL_IP_ENV):2379 -v /run/docker/plugins:/run/docker/plugins -v /var/run/docker.sock:/var/run/docker.sock --name calico-node-libnetwork calico/node-libnetwork /calico`

- `--net=host` Host network is used since the network changes need to occur in the host namespace
- `privileged` since the plugin creates network interfaces
- `-e CALICO_ETCD_AUTHORITY=a.b.c.d:2379` to allow the plugin to find a backend datastore for storing information
- `-v /run/docker/plugins:/run/docker/plugins` allows the docker daemon to discover the plugin
- `-v /var/run/docker.sock:/var/run/docker.sock` allows the plugin to query the docker daemon

## Known limitations
The following is a list of known limitations when using the Calico libnetwork
driver:
-  It is not possible to add multiple networks to a single container.  However,
   once a container endpoint is created, it is possible to manually add 
   additional Calico profiles to that endpoint (effectively adding the 
   container into another network).
-  When using the Calico IPAM driver, it is not yet possible to select which
   IP Pool an IP is assigned from.  Make sure all of your configured IP Pools
   have the same ipip and nat-outgoing settings.

## Troubleshooting

### Logging
Logs are sent to STDOUT. If using Docker these can be viewed with the 
`docker logs` command.


[![Analytics](https://calico-ga-beacon.appspot.com/UA-52125893-3/libnetwork-plugin/README.md?pixel)](https://github.com/igrigorik/ga-beacon)
