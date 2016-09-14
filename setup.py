#!/usr/bin/env python
# Copyright (c) 2016 Tigera, Inc. All rights reserved.
#
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import setuptools

version = '0.9.0'

setuptools.setup(
    name='libnetwork',
    version=version,

    description='Docker libnetwork plugin',

    # The project's main homepage.
    url='https://github.com/projectcalico/libnetwork-plugin/',

    # Author details
    author='Project Calico',
    author_email='maintainers@projectcalico.org',

    # Choose your license
    license='Apache 2.0',

     # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Operating System :: POSIX :: Linux',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Topic :: System :: Networking',
    ],

     # What does your project relate to?
    keywords='calico docker etcd mesos kubernetes rkt openstack',

    packages=setuptools.find_packages(exclude=['ez_setup', 'examples', 'tests']),
    include_package_data=True,
    
    install_requires=['netaddr', 'python-etcd>=0.4.3', 'subprocess32', 'flask', 'gunicorn', 'gevent'],
    dependency_links=[
    "git+https://github.com/projectcalico/python-etcd.git",
    "git+https://github.com/projectcalico/libcalico.git"
    ]
)