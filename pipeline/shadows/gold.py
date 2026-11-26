"""upx-shadows, gold: the scoreboard (with luck lines) and the swing, long-term and benchmark values."""
from pyspark import pipelines as dp
from pyspark.sql import functions as F


def table(name):
    return spark.read.table(name)  # noqa: F821 (spark is given by the pipeline)


@dp.materialized_view(name="gold.shadow_scoreboard",
                      comment="Every shadow on its latest day: family, trades, net, luck line and status (passed, "
                              "above luck, watching, too early, kill).")
def shadow_scoreboard():
    s = table("silver.shadow_status")
    latest = s.agg(F.max("day").alias("day"))
    return s.join(latest, "day")


@dp.materialized_view(name="gold.shadow_values",
                      comment="Swing, long-term and benchmark shadow ledgers per day, with the gain against their pool.")
def shadow_values():
    kind = (F.when(F.col("shadow").startswith("B"), "benchmark")
            .when(F.col("shadow").startswith("L"), "long-term").otherwise("swing"))
    return table("silver.shadow_ledgers").select(
        "day", "shadow", kind.alias("kind"), "capital", "value",
        F.round(F.col("value") - F.col("capital"), 2).alias("gain_rs"),
        F.round((F.col("value") / F.col("capital") - 1) * 100, 2).alias("gain_pct"), "holdings", "closed_trades")
