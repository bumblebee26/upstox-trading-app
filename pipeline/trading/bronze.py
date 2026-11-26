"""upx-trading, bronze: the real pools' journals and balances and the Telegram feed, as raw lines.

Runs at 13:05 and 16:55 IST (lakehouse/sync.py), only when these folders got new files. Dummy money only."""
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


@dp.table(name="bronze.journal_raw", comment="Raw: every journal line (decisions, fills, exits, ratings); each day file is rewritten as the day goes on.")
def journal_raw():
    return raw_lines("journal")


@dp.table(name="bronze.pools_raw", comment="Raw: the balance of each real pool as last saved each day.")
def pools_raw():
    return raw_lines("pools")


@dp.table(name="bronze.feed_raw", comment="Raw: every Telegram message the system sent.")
def feed_raw():
    return raw_lines("feed")
