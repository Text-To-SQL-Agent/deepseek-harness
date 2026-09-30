#!/usr/bin/env bash
set -e

exec node --import tsx/esm apps/cli/src/bin.ts "$@"
