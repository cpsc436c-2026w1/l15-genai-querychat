# Data

Two public files from the NYC Taxi and Limousine Commission (TLC). Neither is committed: `bash data/fetch.sh`
downloads both and checks their SHA-256 against the copies every result in `results/` was computed from.

| file | what it is | source | checked |
|---|---|---|---|
| `taxi_2024-01.parquet` | yellow taxi trips, January 2024: 2,964,624 rows, 19 columns, 50 MB | https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet | 2026-11-02 |
| `taxi_zone_lookup.csv` | taxi zone lookup: LocationID, Borough, Zone, service_zone (265 zones) | https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv | downloaded 2026-11-02 |

Both files are linked from the TLC's [trip record data page](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page),
which also has the data dictionary for the trip columns.

The trips file came to this demo through the DSCI 532 taxi apps, whose `prep_data.py` converts the TLC's CSV
download (`.../trip-data/yellow_tripdata_2024-01.csv`) to Parquet. That CSV address no longer serves the file
(HTTP 403 on 2026-11-02). The copy used here is byte-identical (same SHA-256) to the TLC's own Parquet at the
address in the table, so the fetch script downloads that one.

`harness/db.py` builds `data/taxi.duckdb` from the two files on first use (tables `taxi` and `zones`). It is
gitignored too.
