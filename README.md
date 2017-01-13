[![Build Status](https://semaphoreci.com/api/v1/projects/d51a0276-7939-409e-80ac-aa5df9421fef/510521/badge.svg)](https://semaphoreci.com/calico/libnetwork-plugin)

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

## How to Test It

### On Linux

`make test` is all you need.

### On OSX/Windows

On OSX/Windows you can't run Docker natively. To allow the Makefile to write the build libnetwork-plugin to your host's filesystem and to allow the test to access the Docker daemon via the unix socket, the user id and group id of the docker user are needed. For boot2docker the user id is 1000 and group id 100.

Run `make test` like this: `LOCAL_USER_ID=1000 LOCAL_GROUP_ID=100 make test-containerized`


## Known limitations
The following is a list of known limitations when using the Calico libnetwork
driver:
-  It is not possible to add multiple networks to a single container.  However,
   once a container endpoint is created, it is possible to manually add 
   additional Calico profiles to that endpoint (effectively adding the 
   container into another network).
- IPv6 is not currently supported

## Configuring

To change the prefix used for the interface in containers that Docker runs, set the `CALICO_LIBNETWORK_IFPREFIX` environment variable.

* The default value is "cali"

To enable debug logging set the `CALICO_DEBUG` environment variable.

The plugin creates a Calico profile resource for the Docker network used (e.g. `docker run --net <network> ...`). This is enabled by default. It can be disabled by setting the environment: `CALICO_LIBNETWORK_CREATE_PROFILES=false`.

The plugin can copy Docker container labels to the corresponding Calico workloadendpoint. This feature is disabled by default. It can be enabled by setting the environment: `CALICO_LIBNETWORK_LABEL_ENDPOINTS=true`.

## Workloadendpoint labelling
If you want to use Calico policies you need labels on the Calico workloadendpoint. The plugin can set labels by copying a subset of the Docker container labels.

To enable this feature you need to set the environment: `CALICO_LIBNETWORK_LABEL_ENDPOINTS=true`.

Only container labels starting with `org.projectcalico.label.` are used. This prefix is removed and the remaining key is used a label key in the workloadendpoint.

Example: `docker run --label org.projectcalico.label.foo=bar --net <calico network> <image> ...` will create a workloadendpoint with label `foo=bar`. Of course you can use multiple `--label org.projectcalico.label.<key>=<value>` options.


*NOTE:* the labels are added to the workloadendpoint using an update, because the container information is not available at the moment the workloadendpoint resource is created.

## Troubleshooting

### Logging
Logs are sent to STDOUT. If using Docker these can be viewed with the 
`docker logs` command.

### Monitoring

Check the plugin health by executing API calls.

NetworkDriver:

```
# echo -e "GET /NetworkDriver.GetCapabilities HTTP/1.0\r\n\r\n" | nc -U /run/docker/plugins/calico.sock
HTTP/1.0 200 OK
Content-Type: application/vnd.docker.plugins.v1.1+json
Date: Thu, 08 Dec 2016 10:00:41 GMT
Content-Length: 19

{"Scope":"global"}
```

IpamDriver:

```
# echo -e "GET /IpamDriver.GetCapabilities HTTP/1.0\r\n\r\n" | nc -U /run/docker/plugins/calico-ipam.sock
HTTP/1.0 200 OK
Content-Type: application/vnd.docker.plugins.v1.1+json
Date: Thu, 08 Dec 2016 10:02:51 GMT
Content-Length: 29

{"RequiresMACAddress":false}
```

[![Analytics](https://calico-ga-beacon.appspot.com/UA-52125893-3/libnetwork-plugin/README.md?pixel)](https://github.com/igrigorik/ga-beacon)
