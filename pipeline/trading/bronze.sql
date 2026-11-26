-- upx-trading: the real pools (journals, balances) and the Telegram feed. Runs 13:05 and 16:55 IST.
-- Bronze: each landing line as text, with where and when it came from; parsed in silver (VARIANT).

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

CREATE OR REFRESH STREAMING TABLE bronze.pools_raw
COMMENT 'Raw: the balance of each real pool as last saved each day.'
AS SELECT
  value AS line,
  _metadata.file_path AS _source_file,
  _metadata.file_modification_time AS _file_modified_at,
  current_timestamp() AS _ingested_at
FROM STREAM read_files('/Volumes/upx/bronze/landing/pools/', format => 'text', allowOverwrites => 'true');
