[![Build Status](https://semaphoreci.com/api/v1/projects/d51a0276-7939-409e-80ac-aa5df9421fef/510521/badge.svg)](https://semaphoreci.com/calico/libnetwork-plugin)
[![Circle CI](https://circleci.com/gh/projectcalico/libnetwork-plugin/tree/master.svg?style=svg)](https://circleci.com/gh/projectcalico/libnetwork-plugin/tree/master)
[![Coverage Status](https://coveralls.io/repos/projectcalico/libnetwork-plugin/badge.svg?branch=master&service=github)](https://coveralls.io/github/projectcalico/libnetwork-plugin?branch=master)


#Libnetwork plugin for Calico

This plugin for Docker networking ([libnetwork](https://github.com/docker/libnetwork)) is intended for use with [Project Calico](http://www.projectcalico.org).
Calico can be deployed on Docker using guides from the [calico-docker](https://github.com/projectcalico/calico-docker) repository.

## How to Run It
When deployed using `calicoctl` (see calico-docker) simply pass in the `--libnetwork` flag.
* To run a specific [version](https://github.com/projectcalico/libnetwork-plugin/releases) of the plugin use the `--libnetwork-image` flag.

### With Docker
Prebuilt docker images are available on [DockerHub](https://hub.docker.com/r/calico/node-libnetwork/) with [tags](https://hub.docker.com/r/calico/node-libnetwork/tags/) available for each libnetwork-plugin [release](https://github.com/projectcalico/libnetwork-plugin/releases).

The container needs to be run using 
`docker run -d --privileged --net=host -v /run/docker/plugins:/run/docker/plugins calico/node-libnetwork`
 
* Privileged is required since the container creates network devices.
* Host network is used since the network changes need to occur in the host namespace
* The /run/docker/plugins volume is used to allow the plugin to communicate with Docker.

If you don't have etcd available at localhost:4001 then you need to pass in the location as an environment variable e.g. `-e ETCD_AUTHORITY=1.2.3.4:2379`

### From source
To run the plugin from source use `gunicorn` e.g.
`sudo gunicorn -b unix:///run/docker/plugins/calico.sock libnetwork.driver_plugin:app`

For the full list of recommended options for use in production, see [start.sh](start.sh)
 
For testing out changes, add the `--reload` flag or use `make run-plugin-local` 

Install the dependencies from requirements.txt using `pip install -r requirements.txt`

## Calico networking and IPAM
The plugin provides Calico driver support for both networking, and IPAM.  When 
creating a network in Docker, use the `-d calico` to use the Calico network 
driver, and the `--ipam-driver calico` to use the Calico IPAM driver.

## Known limitations
The following is a list of known limitations when using the Calico libnetwork
driver:
-  Creating a mix of containers which use both the Calico IPAM driver and the
   default IPAM driver is not recommended.  In this case, isolation between
   containers on a "default IPAM" network may not be correctly isolated from
   containers on a "Calico IPAM" network running on the same host.
-  It is not possible to add multiple networks to a single container.  However,
   once a container endpoint is created, it is possible to manually add 
   additional Calico profiles to that endpoint (effectively adding the 
   container into another network).
-  When using the Calico IPAM driver, it is not yet possible to select which
   IP Pool an IP is assigned from.  Make sure all of your configured IP Pools
   have the same ipip and nat-outgoing settings.

## Troubleshooting
### Logging
Logs are sent to STDOUT. If using Docker these can be viewed with the `docker logs` command.
#### Changing the log level
This currently requires a rebuild. Change the line towards the top of the [plugin code](https://github.com/projectcalico/libnetwork-plugin/blob/master/libnetwork/driver_plugin.py)

## Performance
### Datastore Interactions
These don't include interactions from the Docker daemon or felix. These are interactions from the libnetwork-plugin _only_.

The number of reads and writes is dependent on whether Calico IPAM driver is also used.

Datastore interactions using default IPAM:

Operation      | Reads | Writes| Deletes| Notes
---------------|-------|-------|--------|------
DiscoverNew    | 0     | 0     | 0      | None
CreateNetwork  | 0     | 4 (5 if IPv4 and IPv6) | 0      | 2 for creating profile (tags and rules), 1 per IP Pool, and 1 to store the request JSON
CreateEndpoint | 1     | 1     | 0      | Read CreateNetwork JSON and write Endpoint
Join           | 1     | 0     | 0      | Read CreateNetwork JSON
DiscoverDelete | 0     | 0     | 0      | None
DeleteNetwork  | 1     | 0     | 3 (4 if IPv4 and IPv6)     | Delete profile, pool and stored CreateNetwork JSON
DeleteEndpoint | 0     | 0     | 1      | Delete endpoint
Leave          | 0     | 0     | 0      | None


Datastore interactions using Calico IPAM:

Operation      | Reads | Writes| Deletes| Notes
---------------|-------|-------|--------|------
DiscoverNew    | 0     | 0     | 0      | None
RequestPool    | 0     | 0     | 0      | None
CreateNetwork  | 0     | 3     | 0      | 2 for creating profile (tags and rules), and 1 to store the request JSON
RequestAddress | >=2   | >=1   | >=0    | May have multiple reads/writes/deletes depending on contention (see libcalico IPAM)
CreateEndpoint | 3     | 1     | 0      | Read CreateNetwork JSON and IPv4/IPv6 next hops, and write Endpoint
Join           | 2     | 0     | 0      | Read CreateNetwork JSON and Endpoint
DiscoverDelete | 0     | 0     | 0      | None
ReleasePool    | 0     | 0     | 0      | None
DeleteNetwork  | 1     | 0     | 3 (4 if IPv4 and IPv6)     | Delete profile, pool and stored CreateNetwork JSON
ReleaseAddress | >=1   | >=1   | >=0    | May have multiple reads/writes/deletes depending on contention (see libcalico IPAM)
DeleteEndpoint | 0     | 0     | 1      | Delete endpoint
Leave          | 0     | 0     | 0      | None


## Contributing and getting help
See the [main Calico documentation](http://docs.projectcalico.org/en/latest/involved.html)

Further sources of getting help are listed in the [calico-docker](https://github.com/projectcalico/calico-docker#calico-on-docker) repository.[![Analytics](https://ga-beacon.appspot.com/UA-52125893-3/libnetwork-plugin/README.md?pixel)](https://github.com/igrigorik/ga-beacon)
