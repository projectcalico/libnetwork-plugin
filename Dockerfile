FROM alpine
MAINTAINER Tom Denham <tom@projectcalico.org>
ADD dist/amd64/libnetwork-plugin /libnetwork-plugin
ENTRYPOINT ["/libnetwork-plugin"]

