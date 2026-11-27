"""upx-market, silver: NSE daily prices with delivery, deals, filings and board meetings, each once."""
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


def _history_eq():
    """The copied history: bhavcopy stock rows (UDiFF) with that day's delivery, one row per day, stock and series."""
    num = lambda c: F.col(c).cast("double")  # noqa: E731
    bhav = (spark.read.table("bronze.hist_bhavcopy_raw")  # noqa: F821
            # files from before NSE's July 2024 format leave the instrument type empty: every row is a stock row
            .where(F.coalesce(F.col("FinInstrmTp"), F.lit("STK")) == "STK")
            .select(F.to_date("TradDt").alias("day"), F.col("TckrSymb").alias("symbol"), F.col("SctySrs").alias("series"),
                    num("OpnPric").alias("open"), num("HghPric").alias("high"), num("LwPric").alias("low"),
                    num("ClsPric").alias("close"), num("PrvsClsgPric").alias("prev_close"),
                    F.col("TtlTradgVol").cast("bigint").alias("volume"), num("TtlTrfVal").alias("turnover_rs")))
    deliv = (spark.read.table("bronze.hist_delivery_raw")  # noqa: F821
             .select(F.col("trade_date").alias("day"), "symbol", "series",
                     F.col("deliv_qty").cast("bigint").alias("deliv_qty"), F.col("deliv_per").alias("deliv_pct"))
             .dropDuplicates(["day", "symbol", "series"]))
    return (bhav.join(deliv, ["day", "symbol", "series"], "left")
            .withColumn("source", F.lit("nse_history")).withColumn("_priority", F.lit(2)))


@dp.materialized_view(name="silver.nse_eq_daily",
                      comment="NSE open, high, low, close, volume, turnover and delivery % per stock and day: the "
                              "history from 2019 plus every new day (a new day's file wins over the history).")
def nse_eq_daily():
    daily = newest(parsed("bronze.nse_bhav_raw").selectExpr(
        "to_date(v:day::string) AS day", "v:symbol::string AS symbol", "'EQ' AS series",
        "v:open::double AS open", "v:high::double AS high", "v:low::double AS low", "v:close::double AS close",
        "v:prev_close::double AS prev_close", "v:volume::bigint AS volume",
        "v:turnover_lacs::double * 1e5 AS turnover_rs", "v:deliv_qty::bigint AS deliv_qty",
        "v:deliv_pct::double AS deliv_pct", "'nse_daily' AS source", "_file_modified_at"), "day", "symbol")
    both = daily.withColumn("_priority", F.lit(1)).unionByName(_history_eq())
    w = Window.partitionBy("day", "symbol", "series").orderBy("_priority")
    return both.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn", "_priority")


@dp.materialized_view(name="silver.nse_index_daily",
                      comment="Every NSE index per day (incl. India VIX), from the copied history (2019 on).")
def nse_index_daily():
    return (spark.read.table("bronze.hist_indices_raw")  # noqa: F821
            .select(F.col("trade_date").alias("day"), "index_name", "open", "high", "low", "close", "change_pct")
            .dropDuplicates(["day", "index_name"]))


@dp.materialized_view(name="silver.us_daily",
                      comment="US daily bars per ticker (Massive grouped daily), from the copied history (Nov 2024 on).")
def us_daily():
    # no "t" (timestamp): Spark matches names case-insensitively, so it would clash with "T" (ticker); the day
    # comes from the date= folder instead
    bar = "array<struct<T:string,o:double,h:double,l:double,c:double,v:double,vw:double,n:bigint>>"
    return (spark.read.table("bronze.hist_us_raw")  # noqa: F821
            .select("trade_date", F.explode(F.from_json("results", bar)).alias("r"))
            .select(F.col("trade_date").alias("day"), F.col("r.T").alias("symbol"), F.col("r.o").alias("open"),
                    F.col("r.h").alias("high"), F.col("r.l").alias("low"), F.col("r.c").alias("close"),
                    F.col("r.v").alias("volume"), F.col("r.vw").alias("vwap"), F.col("r.n").alias("trades"))
            .dropDuplicates(["day", "symbol"]))


@dp.materialized_view(name="silver.deals", comment="NSE bulk and block deals, each once.")
def deals():
    return (parsed("bronze.nse_deals_raw").where("v:day IS NOT NULL").selectExpr(
        "to_date(v:day::string) AS day", "v:kind::string AS kind", "v:symbol::string AS symbol",
        "v:client::string AS client", "v:side::string AS side", "v:qty::bigint AS qty", "v:price::double AS price",
        "v:qty::double * v:price::double AS value_rs").distinct())


@dp.materialized_view(name="silver.filings", comment="NSE company filings (announcements), each once.")
def filings():
    return (parsed("bronze.nse_filings_raw").where("v:symbol IS NOT NULL").selectExpr(
        "v:symbol::string AS symbol", "try_to_timestamp(v:an_dt::string, 'dd-MMM-yyyy HH:mm:ss') AS filed_at",
        "v:desc::string AS what", "left(v:attchmntText::string, 500) AS detail",
        "v:attchmntFile::string AS link").distinct())


@dp.materialized_view(name="silver.board_meetings",
                      comment="NSE board meetings (results and others), as last seen in the calendar.")
def board_meetings():
    return (parsed("bronze.nse_calendar_raw").where("v:day IS NOT NULL").selectExpr(
        "v:symbol::string AS symbol", "to_date(v:day::string) AS day", "v:purpose::string AS purpose",
        "to_date(v:saved_on::string) AS saved_on")
        .groupBy("symbol", "day", "purpose").agg(F.max("saved_on").alias("last_seen")))
