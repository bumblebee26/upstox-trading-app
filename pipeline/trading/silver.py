"""upx-trading, silver: each journal event, closed trade, pool balance and Telegram message once."""
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


@dp.materialized_view(name="silver.trade_events",
                      comment="Every journal event once (newest copy per event_id): reviews, fills, exits, stops, "
                              "ratings, blocks, decisions.")
def trade_events():
    df = parsed("bronze.journal_raw").where("v:event_id IS NOT NULL").selectExpr(
        "v:event_id::string AS event_id", "v:event::string AS event",
        "coalesce(v:pool::string, 'intraday') AS pool",
        "to_date(regexp_extract(_source_file, '([0-9]{4}-[0-9]{2}-[0-9]{2})', 1)) AS trade_date",
        "v:written_at::string AS written_at", "v:at::string AS at_ist", "v:symbol::string AS symbol",
        "v:side::string AS side", "v:setup::string AS setup", "v:qty::int AS qty", "v:price::double AS price",
        "v:net_rs::double AS net_rs", "v:charges_rs::double AS charges_rs", "v:reason::string AS reason",
        "v:review_id::string AS review_id", "v:rating::string AS rating", "v AS raw", "_file_modified_at")
    return newest(df, "event_id")


@dp.materialized_view(name="silver.trades",
                      comment="Closed trades of the real pools: one row per exit, with its setup and the owner rating "
                              "(👍/👎) when there is one.")
def trades():
    ev = spark.read.table("silver.trade_events")  # noqa: F821
    setups = ev.where("event = 'review'").groupBy("review_id").agg(F.any_value("setup").alias("setup"))
    ratings = ev.where("event = 'rating'").groupBy("review_id").agg(F.max_by("rating", "written_at").alias("rating"))
    return (ev.where("event = 'exit'")
            .join(setups, "review_id", "left").join(ratings, "review_id", "left")
            .select("trade_date", "pool", "symbol", "qty", F.col("price").alias("exit_price"), "net_rs",
                    "charges_rs", F.col("reason").alias("exit_reason"), "review_id",
                    F.coalesce("setup", F.lit("not recorded")).alias("setup"), "rating",
                    (F.col("net_rs") > 0).alias("won"), "written_at"))


@dp.materialized_view(name="silver.pool_days", comment="The balance of each real pool at the end of each day.")
def pool_days():
    df = parsed("bronze.pools_raw").selectExpr(
        "to_date(v:day::string) AS day", "v:pool::string AS pool", "v:balance::double AS balance",
        "v:starting_capital::double AS starting_capital", "v:realized_today::double AS realized_today",
        "v:open_positions::int AS open_positions", "_file_modified_at")
    return newest(df, "day", "pool")


@dp.materialized_view(name="silver.feed", comment="Every Telegram message the system sent (the Feed tab of the app).")
def feed():
    df = parsed("bronze.feed_raw").selectExpr(
        "try_to_timestamp(v:ts::string) AS sent_at", "v:id::bigint AS message_id", "v:text::string AS text",
        "v:reply_to::bigint AS reply_to", "_file_modified_at")
    return newest(df, "message_id")
