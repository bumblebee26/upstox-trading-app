"""upx-market, gold: big deals, and data freshness across all three pipelines."""
from pyspark import pipelines as dp
from pyspark.sql import functions as F


def table(name):
    return spark.read.table(name)  # noqa: F821 (spark is given by the pipeline)


@dp.materialized_view(name="gold.deals_board",
                      comment="NSE bulk and block deals of ₹1 crore and more in the last 30 days.")
def deals_board():
    return (table("silver.deals").where((F.col("value_rs") >= 1e7) &
                                        (F.col("day") >= F.date_sub(F.current_date(), 30)))
            .select("day", "kind", "symbol", "client", "side", "qty", "price",
                    F.round(F.col("value_rs") / 1e7, 2).alias("value_cr")))


@dp.materialized_view(name="gold.data_freshness",
                      comment="The newest day each source has reached, to spot a job that stopped.")
def data_freshness():
    sources = [("journal", "upx.silver.trade_events", "trade_date"), ("pools", "upx.silver.pool_days", "day"),
               ("shadow trades", "upx.silver.shadow_trades", "day"), ("shadow status", "upx.silver.shadow_status", "day"),
               ("shadow ledgers", "upx.silver.shadow_ledgers", "day"), ("NSE bhavcopy", "silver.nse_eq_daily", "day"),
               ("NSE deals", "silver.deals", "day")]
    out = None
    for name, tbl, col in sources:
        row = table(tbl).agg(F.max(col).alias("newest_day")).select(F.lit(name).alias("source"), "newest_day")
        out = row if out is None else out.unionByName(row)
    return out
