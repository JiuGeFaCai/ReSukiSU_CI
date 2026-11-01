#!/usr/bin/env bash
set -euo pipefail

export SYNC_NAME=SukiSU-Ultra
export TAG_PREFIX=SukiSU
export ARTIFACT_NAME=Manager
export APK_PREFIX=SukiSU

exec bash "$(dirname -- "${BASH_SOURCE[0]}")/sync-manager.sh"
