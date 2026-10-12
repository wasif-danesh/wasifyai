#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "$0")/lib.sh"
[ "$CONTAINER_ENGINE" = "podman" ] && export KIND_EXPERIMENTAL_PROVIDER=podman
kind delete cluster --name wasifyai
