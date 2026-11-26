-- upx-market: NSE files (bhavcopy with delivery, deals, filings, results calendar) and the copied history.
-- Runs 20:05 IST, after the NSE evening job.
-- Bronze: each landing line as text, with where and when it came from; parsed in silver (VARIANT).

CREATE OR REFRESH STREAMING TABLE bronze.nse_bhav_raw
COMMENT 'Raw: NSE delivery bhavcopy rows.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/nse_bhav/', format => 'text', allowOverwrites => 'true');

CREATE OR REFRESH STREAMING TABLE bronze.nse_deals_raw
COMMENT 'Raw: NSE bulk and block deals.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/nse_deals/', format => 'text', allowOverwrites => 'true');

CREATE OR REFRESH STREAMING TABLE bronze.nse_filings_raw
COMMENT 'Raw: NSE company filings.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/nse_filings/', format => 'text', allowOverwrites => 'true');

CREATE OR REFRESH STREAMING TABLE bronze.nse_calendar_raw
COMMENT 'Raw: NSE board meetings ahead.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/nse_calendar/', format => 'text', allowOverwrites => 'true');
