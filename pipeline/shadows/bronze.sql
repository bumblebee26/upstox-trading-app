-- upx-shadows: the rule-based paper shadows (intraday trades, status and luck lines, swing and long-term
-- ledgers, NIFTYBEES benchmarks). Runs 17:30 IST, after the shadows job.
-- Bronze: each landing line as text, with where and when it came from; parsed in silver (VARIANT).

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
