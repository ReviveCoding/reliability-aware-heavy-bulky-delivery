SELECT
  CAST(date AS DATE) AS monitoring_date,
  station_id,
  service_type,
  AVG(ABS(actual_duration - predicted_duration)) AS duration_mae,
  AVG(CASE WHEN actual_duration <= duration_p90 THEN 1.0 ELSE 0.0 END) AS p90_coverage,
  AVG(reference_fallback) AS reference_fallback_rate,
  COUNT(*) AS order_count
FROM planning_orders_rass
GROUP BY 1,2,3;
