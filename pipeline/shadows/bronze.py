"""upx-shadows, bronze: the rule-based paper shadows' results, as raw lines.

Runs at 17:30 IST (lakehouse/sync.py), after the shadows job, only when these folders got new files."""
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


@dp.table(name="bronze.shadow_trades_raw", comment="Raw: intraday shadow trades.")
def shadow_trades_raw():
    return raw_lines("shadow_trades")


@dp.table(name="bronze.shadow_status_raw", comment="Raw: the family, luck line and status of each shadow per day.")
def shadow_status_raw():
    return raw_lines("shadow_status")


@dp.table(name="bronze.shadow_ledgers_raw", comment="Raw: swing, long-term and benchmark shadow ledgers per day.")
def shadow_ledgers_raw():
    return raw_lines("shadow_ledgers")
