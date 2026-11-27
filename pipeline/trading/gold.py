"""upx-trading, gold: what the dashboard, the app and the reviews read about the real pools (paper results)."""
from pyspark import pipelines as dp
from pyspark.sql import Window
from pyspark.sql import functions as F


def table(name):
    return spark.read.table(name)  # noqa: F821 (spark is given by the pipeline)

WIN = F.avg(F.when(F.col("won"), 1.0).otherwise(0.0))


@dp.materialized_view(name="gold.trading_daily",
                      comment="Each real pool per day: trades, wins, net after charges, end balance, and whether the "
                              "balance moved by exactly the day net.")
def trading_daily():
    t = (table("silver.trades").groupBy(F.col("trade_date").alias("day"), "pool")
         .agg(F.count("*").alias("trades"), F.sum(F.col("won").cast("int")).alias("wins"),
              F.round(F.sum("net_rs"), 2).alias("net_rs"), F.round(F.sum("charges_rs"), 2).alias("charges_rs")))
    b = table("silver.pool_days").withColumn(
        "prev_balance", F.lag("balance").over(Window.partitionBy("pool").orderBy("day"))).select(
        "day", "pool", "balance", "prev_balance")
    j = t.join(b, ["day", "pool"], "full")
    net = F.coalesce("net_rs", F.lit(0.0))
    return j.select(
        "day", "pool", F.coalesce("trades", F.lit(0)).alias("trades"), F.coalesce("wins", F.lit(0)).alias("wins"),
        net.alias("net_rs"), F.coalesce("charges_rs", F.lit(0.0)).alias("charges_rs"), "balance",
        F.when(F.col("prev_balance").isNull() | F.col("balance").isNull(), None)
         .otherwise(F.abs(F.col("balance") - F.col("prev_balance") - net) < 1).alias("reconciled"))


@dp.materialized_view(name="gold.track_record",
                      comment="Last 90 days by pool and setup: trades, win rate and average net (the reviewers' base rate).")
def track_record():
    return (table("silver.trades").where(F.col("trade_date") >= F.date_sub(F.current_date(), 90))
            .groupBy("pool", "setup")
            .agg(F.count("*").alias("trades"), F.round(WIN * 100, 1).alias("win_pct"),
                 F.round(F.sum("net_rs"), 2).alias("net_rs"), F.round(F.avg("net_rs"), 2).alias("avg_net_rs")))


@dp.materialized_view(name="gold.trading_by_setup", comment="All-time by pool and setup.")
def trading_by_setup():
    return (table("silver.trades").groupBy("pool", "setup")
            .agg(F.count("*").alias("trades"), F.round(WIN * 100, 1).alias("win_pct"),
                 F.round(F.sum("net_rs"), 2).alias("net_rs"), F.min("trade_date").alias("first_day"),
                 F.max("trade_date").alias("last_day")))


@dp.materialized_view(name="gold.your_calls",
                      comment="The owner ratings against what each trade did: how often a 👍 or a 👎 was right.")
def your_calls():
    right = F.when(F.col("rating").isNull(), None).when((F.col("rating") == "up") == F.col("won"), 1.0).otherwise(0.0)
    return (table("silver.trades").groupBy("pool", F.coalesce("rating", F.lit("unrated")).alias("rating"))
            .agg(F.count("*").alias("trades"), F.sum(F.col("won").cast("int")).alias("won"),
                 F.round(F.sum("net_rs"), 2).alias("net_rs"), F.round(F.avg(right) * 100, 1).alias("call_right_pct")))


@dp.materialized_view(name="gold.trade_timeline",
                      comment="Who took how long on each trade: facts, the AI deciding, the council, approval (auto or "
                              "the owner), placing, the fill, holding and the total from first look to exit.")
def trade_timeline():
    ev = table("silver.trade_events").where("event = 'exit'").where("raw:timeline IS NOT NULL")
    t = "raw:timeline"
    return ev.selectExpr(
        "trade_date", "pool", "symbol", "review_id", "net_rs",
        f"{t}.first_look::string AS first_look", f"{t}.facts_s::double AS facts_s",
        f"{t}.ai_decide_s::double AS ai_decide_s", f"{t}.council_s::double AS council_s",
        f"{t}.approval::string AS approval", f"{t}.approval_s::double AS approval_s",
        f"{t}.placing_s::double AS placing_s", f"{t}.fill_s::double AS fill_s",
        f"{t}.hold_min::double AS hold_min", f"{t}.total_min::double AS total_min")
