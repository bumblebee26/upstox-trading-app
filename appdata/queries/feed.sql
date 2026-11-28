-- The last 300 Telegram messages (TFeed tab), newest first.
SELECT sent_at, message_id, text, reply_to FROM upx.silver.feed ORDER BY sent_at DESC LIMIT 300
