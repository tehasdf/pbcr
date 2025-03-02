#!/usr/bin/env bash

set -eux

dir=$(dirname "${BASH_SOURCE[0]}")

pbcr run \
    docker.io/library/nginx:sha256:7f797701ded5055676d656f11071f84e2888548a2e7ed12a4977c28ef6114b17 \
    --rm \
    -n c1 \
    -v "${dir}/default.conf:/etc/nginx/conf.d/default.conf"
