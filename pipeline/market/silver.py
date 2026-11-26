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


@dp.materialized_view(name="silver.nse_eq_daily",
                      comment="NSE open, high, low, close, volume, turnover and delivery % per stock and day.")
def nse_eq_daily():
    df = parsed("bronze.nse_bhav_raw").selectExpr(
        "to_date(v:day::string) AS day", "v:symbol::string AS symbol", "'EQ' AS series",
        "v:open::double AS open", "v:high::double AS high", "v:low::double AS low", "v:close::double AS close",
        "v:prev_close::double AS prev_close", "v:volume::bigint AS volume",
        "v:turnover_lacs::double * 1e5 AS turnover_rs", "v:deliv_qty::bigint AS deliv_qty",
        "v:deliv_pct::double AS deliv_pct", "'nse_daily' AS source", "_file_modified_at")
    return newest(df, "day", "symbol")


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
