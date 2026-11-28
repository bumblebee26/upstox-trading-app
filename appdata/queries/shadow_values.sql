-- Swing, long-term and NIFTYBEES benchmark shadow values per day (last 400 days).
SELECT day, shadow, kind, capital, value, gain_rs, gain_pct, holdings, closed_trades
FROM upx.gold.shadow_values WHERE day >= date_sub(current_date(), 400) ORDER BY day
