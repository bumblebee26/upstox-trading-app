-- Bronze: each landing folder as raw JSON lines (text), with where and when each line came from.
-- Lines are parsed in silver (VARIANT), so a new field in a file never breaks loading.
-- Files are rewritten when their content changes, so a line can arrive twice; silver keeps the newest.

CREATE OR REFRESH STREAMING TABLE bronze.journal_raw
COMMENT 'Raw: every journal line (decisions, fills, exits, ratings); each day file is rewritten as the day goes on.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/journal/', format => 'text', allowOverwrites => 'true');

CREATE OR REFRESH STREAMING TABLE bronze.feed_raw
COMMENT 'Raw: every Telegram message the system sent.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/feed/', format => 'text', allowOverwrites => 'true');

CREATE OR REFRESH STREAMING TABLE bronze.shadow_trades_raw
COMMENT 'Raw: intraday shadow trades.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/shadow_trades/', format => 'text', allowOverwrites => 'true');

CREATE OR REFRESH STREAMING TABLE bronze.shadow_status_raw
COMMENT 'Raw: the family, luck line and status of each shadow per day.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/shadow_status/', format => 'text', allowOverwrites => 'true');

CREATE OR REFRESH STREAMING TABLE bronze.shadow_ledgers_raw
COMMENT 'Raw: swing, long-term and benchmark shadow ledgers per day.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/shadow_ledgers/', format => 'text', allowOverwrites => 'true');

CREATE OR REFRESH STREAMING TABLE bronze.pools_raw
COMMENT 'Raw: the balance of each real pool as last saved each day.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/pools/', format => 'text', allowOverwrites => 'true');

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
