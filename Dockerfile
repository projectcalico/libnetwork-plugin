# Copyright 2015 Metaswitch Networks
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
FROM gliderlabs/alpine:latest
MAINTAINER Tom Denham <tom@projectcalico.org>

COPY requirements.txt /

RUN apk --update add python py-setuptools iproute2 && \
    apk add --virtual build-dependencies git python-dev build-base curl bash py-pip alpine-sdk libffi-dev openssl-dev && \
    pip install -r requirements.txt && \
    apk del build-dependencies && rm -rf /var/cache/apk/*

COPY start.sh /
COPY libnetwork /calico_containers/libnetwork_plugin

ENTRYPOINT ["./start.sh"]
