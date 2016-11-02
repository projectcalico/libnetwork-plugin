FROM alpine
MAINTAINER Tom Denham <tom@projectcalico.org>
ADD dist/libnetwork-plugin /libnetwork-plugin
ENTRYPOINT ["/libnetwork-plugin"]

