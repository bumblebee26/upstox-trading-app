"""upx-market, bronze: the daily NSE files as raw lines, and the history copied once from the old system
(NSE bhavcopy since 2019, delivery since Aug 2019, indices since 2019, US daily since Nov 2024).

Runs at 20:05 IST (lakehouse/sync.py), after the NSE evening job, only when these folders got new files."""
from pyspark import pipelines as dp
from pyspark.sql import functions as F

LANDING = "/Volumes/upx/bronze/landing"
HISTORY = "/Volumes/upx/bronze/history"


def raw_lines(folder):
    """Each line of the folder's JSON-lines files as text, with where and when it came from. A file rewritten
    with new content is read again (silver keeps the newest copy of each record)."""
    return (spark.readStream.format("cloudFiles")  # noqa: F821 (spark is given by the pipeline)
            .option("cloudFiles.format", "text")
            .option("cloudFiles.allowOverwrites", "true")
            .load(f"{LANDING}/{folder}/")
            .select(F.col("value").alias("line"),
                    F.col("_metadata.file_path").alias("_source_file"),
                    F.col("_metadata.file_modification_time").alias("_file_modified_at"),
                    F.current_timestamp().alias("_ingested_at")))


@dp.table(name="bronze.nse_bhav_raw", comment="Raw: NSE delivery bhavcopy rows.")
def nse_bhav_raw():
    return raw_lines("nse_bhav")


@dp.table(name="bronze.nse_deals_raw", comment="Raw: NSE bulk and block deals.")
def nse_deals_raw():
    return raw_lines("nse_deals")


@dp.table(name="bronze.nse_filings_raw", comment="Raw: NSE company filings.")
def nse_filings_raw():
    return raw_lines("nse_filings")


@dp.table(name="bronze.nse_calendar_raw", comment="Raw: NSE board meetings ahead.")
def nse_calendar_raw():
    return raw_lines("nse_calendar")


# ---- History (files copied once by lakehouse/history_copy.py; read once, then nothing new arrives) ------------

def history(folder, fmt, **options):
    """A history folder's files with where each came from and its trading day (from the date=YYYY-MM-DD folder)."""
    reader = spark.readStream.format("cloudFiles").option("cloudFiles.format", fmt)  # noqa: F821
    for k, v in options.items():
        reader = reader.option(k, v)
    return (reader.option("cloudFiles.partitionColumns", "").load(f"{HISTORY}/{folder}/")
            .withColumn("_source_file", F.col("_metadata.file_path"))
            .withColumn("trade_date", F.to_date(F.regexp_extract("_metadata.file_path", r"date=(\d{4}-\d{2}-\d{2})", 1))))


@dp.table(name="bronze.hist_bhavcopy_raw", comment="History: NSE bhavcopy (UDiFF CSV, all columns as text), 2019 on.")
def hist_bhavcopy_raw():
    return history("nse", "csv", header="true", pathGlobFilter="*.csv", **{
        "cloudFiles.inferColumnTypes": "false", "cloudFiles.schemaEvolutionMode": "rescue"})


@dp.table(name="bronze.hist_delivery_raw", comment="History: NSE delivery quantity and % per stock, Aug 2019 on.")
def hist_delivery_raw():
    return history("nse_delivery", "json", pathGlobFilter="*.jsonl", rescuedDataColumn="_rescued_data",
                   schema="symbol STRING, series STRING, deliv_qty DOUBLE, deliv_per DOUBLE, _rescued_data STRING")


@dp.table(name="bronze.hist_indices_raw", comment="History: every NSE index (incl. India VIX), daily, 2019 on.")
def hist_indices_raw():
    return history("nse_indices", "json", pathGlobFilter="*.jsonl", rescuedDataColumn="_rescued_data",
                   schema="index_name STRING, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, change_pct DOUBLE, "
                          "_rescued_data STRING")


@dp.table(name="bronze.hist_us_raw", comment="History: US daily bars for every ticker (Massive), Nov 2024 on.")
def hist_us_raw():
    return history("massive", "json", multiLine="true", pathGlobFilter="*.json", **{
        "cloudFiles.inferColumnTypes": "true", "cloudFiles.schemaHints": "results STRING",
        "cloudFiles.schemaEvolutionMode": "rescue"})
