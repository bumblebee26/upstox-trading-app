"""upx-market, bronze: the daily NSE files, as raw lines (the copied history is added once its inventory is read).

Runs at 20:05 IST (lakehouse/sync.py), after the NSE evening job, only when these folders got new files."""
from pyspark import pipelines as dp
from pyspark.sql import functions as F

LANDING = "/Volumes/upx/bronze/landing"


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
