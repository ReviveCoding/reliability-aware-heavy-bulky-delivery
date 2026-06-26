WITH daily AS (
  SELECT
    CAST(date AS DATE) AS service_date,
    station_id,
    service_type,
    SUM(demand) AS demand_units
  FROM demand
  GROUP BY 1, 2, 3
)
SELECT
  service_date,
  station_id,
  service_type,
  demand_units,
  AVG(demand_units) OVER (
    PARTITION BY station_id, service_type
    ORDER BY service_date
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ) AS rolling_7d_demand
FROM daily
ORDER BY station_id, service_type, service_date;
