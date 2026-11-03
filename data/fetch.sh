#!/usr/bin/env bash
# Download the two NYC TLC files into data/ and check them against the copies the results were computed from.
#   bash data/fetch.sh
set -euo pipefail
cd "$(dirname "$0")"
get() {  # url file sha256
  [ -f "$2" ] || curl -fL --progress-bar -o "$2" "$1"
  echo "$3  $2" | sha256sum -c - 2>/dev/null || shasum -a 256 -c <(echo "$3  $2")
}
get https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet taxi_2024-01.parquet \
    c4d59da7bbc8abaeeeb1727947ee93d9891a71acb42854bd80db1571b2030510
get https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv taxi_zone_lookup.csv \
    1a99e105092230f8620f301edcca7f80d3080642ff404d28ed957d3fa222c8ed
