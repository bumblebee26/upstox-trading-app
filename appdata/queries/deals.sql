-- Bulk and block deals of ₹1 crore and more, last 30 days.
SELECT day, kind, symbol, client, side, qty, price, value_cr FROM upx.gold.deals_board ORDER BY day DESC, value_cr DESC
