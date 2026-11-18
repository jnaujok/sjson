#!/bin/sh
# Downloads the benchmark inputs into benchmarks/data (or $SJSON_BENCH_DATA):
#  - the UCI v2.6 schema (US Air Force Open Arsenal, public release; its
#    messages carry uci:version 006.000)
#  - the simdjson-data corpus of real-world JSON (Twitter, GitHub, Amazon,
#    Semantic Scholar, ...)
set -e
DATA=${SJSON_BENCH_DATA:-$(dirname "$0")/data}
mkdir -p "$DATA"
cd "$DATA"
[ -d uci ] || git clone -q --depth 1 https://github.com/open-arsenal/uci uci
mkdir -p uci-schema
python3 -I -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall('uci-schema')" \
    "uci/UCI Release Documentation - UCI Schema/03_UCI-STD-002_Rev6_UCI_Schema_v2_6-CDRL.zip"
[ -d simdjson-data ] || git clone -q --depth 1 https://github.com/simdjson/simdjson-data simdjson-data
echo "data ready in $DATA"
