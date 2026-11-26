"""upx-shadows, silver: shadow trades, statuses and ledger values, each once."""
from pyspark import pipelines as dp
from pyspark.sql import Window
from pyspark.sql import functions as F


def parsed(table):
    """The bronze lines as VARIANT values (v); unreadable lines are dropped."""
    return (spark.read.table(table)  # noqa: F821 (spark is given by the pipeline)
            .selectExpr("try_parse_json(line) AS v", "_source_file", "_file_modified_at")
            .where("v IS NOT NULL"))


def newest(df, *keys):
    """One row per key: the copy from the most recently modified file."""
    w = Window.partitionBy(*keys).orderBy(F.col("_file_modified_at").desc())
    return df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn", "_file_modified_at")


@dp.materialized_view(name="silver.shadow_trades",
                      comment="Intraday shadow trades (paper, rule-based), one per variant, stock and entry time.")
def shadow_trades():
    df = parsed("bronze.shadow_trades_raw").selectExpr(
        "to_date(v:day::string) AS day", "v:variant::string AS variant", "v:symbol::string AS symbol",
        "v:side::string AS side", "v:entry_time::string AS entry_time", "v:entry::double AS entry",
        "v:exit_time::string AS exit_time", "v:exit::double AS exit_price", "v:exit_reason::string AS exit_reason",
        "v:qty::int AS qty", "v:charges_rs::double AS charges_rs", "v:net_rs::double AS net_rs", "v:r::double AS r",
        "_file_modified_at")
    return newest(df, "day", "variant", "symbol", "entry_time")


@dp.materialized_view(name="silver.shadow_status",
                      comment="Family, trades, net result, luck line and status of each shadow, per day.")
def shadow_status():
    df = parsed("bronze.shadow_status_raw").selectExpr(
        "to_date(v:day::string) AS day", "v:variant::string AS variant", "v:family::string AS family",
        "v:trades::int AS trades", "v:net_rs::double AS net_rs", "v:avg_trade_rs::double AS avg_trade_rs",
        "v:luck_line::double AS luck_line", "v:status::string AS status", "_file_modified_at")
    return newest(df, "day", "variant")


@dp.materialized_view(name="silver.shadow_ledgers",
                      comment="Value of each swing, long-term and NIFTYBEES benchmark shadow ledger, per day.")
def shadow_ledgers():
    df = parsed("bronze.shadow_ledgers_raw").selectExpr(
        "to_date(v:day::string) AS day", "v:id::string AS shadow", "v:capital::double AS capital",
        "v:cash::double AS cash", "v:value::double AS value", "v:holdings::int AS holdings",
        "v:closed::int AS closed_trades", "_file_modified_at")
    return newest(df, "day", "shadow")
