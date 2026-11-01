#!/usr/bin/env bash
set -euo pipefail

export SYNC_NAME=KowSU
export TAG_PREFIX=KowSU
export ARTIFACT_NAME=manager
export APK_PREFIX=KowSU

exec bash "$(dirname -- "${BASH_SOURCE[0]}")/sync-manager.sh"
