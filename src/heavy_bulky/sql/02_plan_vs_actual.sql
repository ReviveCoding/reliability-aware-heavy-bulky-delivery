SELECT
  r.route_id,
  r.station_id,
  r.predicted_route_minutes,
  r.p90_route_minutes,
  SUM(o.actual_duration) + r.travel_minutes AS realized_base_route_minutes,
  (SUM(o.actual_duration) + r.travel_minutes) - r.predicted_route_minutes AS duration_residual,
  r.failure_risk,
  r.predicted_window_violation_minutes,
  r.p90_window_violation_minutes
FROM optimized_routes AS r
JOIN route_members AS m ON r.route_id = m.route_id
JOIN planning_orders AS o ON m.order_id = o.order_id
GROUP BY
  r.route_id,
  r.station_id,
  r.predicted_route_minutes,
  r.p90_route_minutes,
  r.travel_minutes,
  r.failure_risk,
  r.predicted_window_violation_minutes,
  r.p90_window_violation_minutes
ORDER BY r.route_id;
