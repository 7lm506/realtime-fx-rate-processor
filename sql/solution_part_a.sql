/*
 * FX RATES LED DISPLAY - PART A: HOURLY BATCH PROCESSING
 * 
 * Purpose: Calculate current FX rates and percentage change vs yesterday 5PM NY time
 * Schedule: Run every 1 hour
 * Scope: 5 currency pairs
 * 
 * Key Design Decisions:
 * 1. "Yesterday 5PM NY" = Last rate at or before 5PM EST/EDT on previous calendar day
 * 2. Active rate = most recent rate for a pair AND not older than 30 seconds
 * 3. Zero rates are considered invalid and filtered out
 * 4. Timezone: NYC follows EST (UTC-5) or EDT (UTC-4) with DST transitions
 * 5. Output format: "EUR/USD",1.08081,"-0.208%" (currency/rate/change)
 */

-- ============================================================================
-- CONFIGURATION VARIABLES
-- ============================================================================
-- Current execution time (in production, use CURRENT_TIMESTAMP)
-- For testing purposes, you can replace with a specific timestamp
WITH config AS (
    SELECT 
        CURRENT_TIMESTAMP AS execution_time,
        30 AS active_window_seconds,  -- Rates older than this are considered stale
        5 AS display_currency_pairs    -- Number of pairs to process
),

-- ============================================================================
-- STEP 1: IDENTIFY ACTIVE RATES (Last rate per pair, within 30 seconds)
-- ============================================================================
latest_rates AS (
    SELECT 
        event_id,
        event_time,
        ccy_couple,
        rate,
        -- Rank rates by recency for each currency pair
        ROW_NUMBER() OVER (
            PARTITION BY ccy_couple 
            ORDER BY event_time DESC, event_id DESC
        ) AS recency_rank,
        -- Calculate age of the rate
        EXTRACT(EPOCH FROM (
            (SELECT execution_time FROM config) - 
            TO_TIMESTAMP(event_time / 1000.0)
        )) AS rate_age_seconds
    FROM fx_rates
    WHERE 
        -- Filter out invalid rates (zero or negative)
        rate > 0
        -- Performance optimization: only scan recent data
        AND event_time >= (
            EXTRACT(EPOCH FROM (SELECT execution_time FROM config) - INTERVAL '1 minute')::BIGINT * 1000
        )
),

active_rates AS (
    SELECT 
        event_id,
        event_time,
        ccy_couple,
        rate
    FROM latest_rates
    WHERE 
        -- Must be the most recent rate for the currency pair
        recency_rank = 1
        -- Must not be older than 30 seconds
        AND rate_age_seconds <= (SELECT active_window_seconds FROM config)
),

-- ============================================================================
-- STEP 2: CALCULATE YESTERDAY 5PM NY TIME
-- ============================================================================
reference_time AS (
    SELECT 
        execution_time,
        -- Calculate yesterday's date at 5PM NY time
        -- Subtract 1 day and set time to 17:00:00 (5PM)
        (DATE(execution_time AT TIME ZONE 'America/New_York') - INTERVAL '1 day' + TIME '17:00:00') 
            AT TIME ZONE 'America/New_York' 
            AT TIME ZONE 'UTC' AS yesterday_5pm_utc
    FROM config
),

-- ============================================================================
-- STEP 3: GET YESTERDAY'S 5PM RATES (Last rate at or before 5PM NY)
-- ============================================================================
-- First, get all rates up to yesterday 5PM for each currency pair
rates_until_5pm AS (
    SELECT 
        ccy_couple,
        rate,
        event_time,
        event_id,
        ROW_NUMBER() OVER (
            PARTITION BY ccy_couple 
            ORDER BY event_time DESC, event_id DESC
        ) AS rank_desc
    FROM fx_rates
    WHERE 
        -- Only rates at or before yesterday 5PM NY
        TO_TIMESTAMP(event_time / 1000.0) <= (SELECT yesterday_5pm_utc FROM reference_time)
        -- Filter out invalid rates
        AND rate > 0
),

yesterday_rates AS (
    SELECT 
        ccy_couple,
        rate AS yesterday_rate,
        event_time AS yesterday_event_time
    FROM rates_until_5pm
    WHERE rank_desc = 1  -- Get the most recent rate before 5PM
),

-- ============================================================================
-- STEP 4: CALCULATE PERCENTAGE CHANGE
-- ============================================================================
rate_changes AS (
    SELECT 
        ar.ccy_couple,
        ar.rate AS current_rate,
        yr.yesterday_rate,
        -- Calculate percentage change
        CASE 
            WHEN yr.yesterday_rate IS NULL THEN NULL
            ELSE ((ar.rate - yr.yesterday_rate) / yr.yesterday_rate * 100)
        END AS pct_change,
        ar.event_time AS current_event_time,
        yr.yesterday_event_time
    FROM active_rates ar
    LEFT JOIN yesterday_rates yr 
        ON ar.ccy_couple = yr.ccy_couple
)

-- ============================================================================
-- STEP 5: FORMAT OUTPUT FOR LED DISPLAY
-- ============================================================================
SELECT 
    -- Format currency pair: EURUSD -> "EUR/USD"
    '"' || SUBSTRING(ccy_couple, 1, 3) || '/' || SUBSTRING(ccy_couple, 4, 3) || '"' AS ccy_couple,
    
    -- Format current rate with 5 decimal places (standard FX precision)
    ROUND(current_rate::NUMERIC, 5) AS rate,
    
    -- Format percentage change with sign and percentage symbol
    CASE 
        WHEN pct_change IS NULL THEN '"N/A"'
        WHEN pct_change >= 0 THEN '"+' || ROUND(pct_change::NUMERIC, 3)::TEXT || '%"'
        ELSE '"-' || ROUND(ABS(pct_change)::NUMERIC, 3)::TEXT || '%"'
    END AS change
    
FROM rate_changes
ORDER BY ccy_couple;

/*
 * ============================================================================
 * EXPECTED OUTPUT FORMAT:
 * ============================================================================
 * ccy_couple | rate      | change
 * -----------+-----------+---------
 * "AUD/USD"  | 0.65490   | "-0.208%"
 * "EUR/GBP"  | 0.85619   | "+0.150%"
 * "EUR/USD"  | 1.08079   | "-0.208%"
 * "GBP/USD"  | 1.26230   | "+1.500%"
 * "NZD/USD"  | 0.61642   | "N/A"
 * 
 * Notes:
 * - Only currency pairs with active rates are shown
 * - N/A appears when no yesterday reference rate exists
 * - Positive changes show "+" prefix, negative changes show "-" prefix
 * - All values are properly quoted for LED display compatibility
 * 
 * ============================================================================
 * TESTING INSTRUCTIONS:
 * ============================================================================
 * 
 * 1. Create test table and load sample data:
 *    CREATE TABLE fx_rates (
 *        event_id BIGINT PRIMARY KEY,
 *        event_time BIGINT NOT NULL,
 *        ccy_couple VARCHAR(6) NOT NULL,
 *        rate DOUBLE PRECISION NOT NULL
 *    );
 *    
 *    COPY fx_rates FROM '/path/to/rates_sample.csv' 
 *    WITH (FORMAT CSV, HEADER true);
 * 
 * 2. Run this query to verify output format
 * 
 * 3. To test with specific timestamp, replace CURRENT_TIMESTAMP in config CTE
 * 
 * ============================================================================
 * PERFORMANCE NOTES:
 * ============================================================================
 * 
 * For optimal performance with hourly execution on 5 currency pairs:
 * 
 * 1. Create indexes:
 *    CREATE INDEX idx_rates_ccy_time ON fx_rates(ccy_couple, event_time DESC);
 *    CREATE INDEX idx_rates_time ON fx_rates(event_time DESC) 
 *    WHERE rate > 0;
 * 
 * 2. Expected execution time: <1 second for ~18M rows/hour
 * 
 * 3. Memory usage: Minimal, window functions are memory-efficient
 * 
 * 4. Consider partitioning by date if table grows beyond 100M rows:
 *    CREATE TABLE fx_rates (
 *        ...
 *    ) PARTITION BY RANGE (event_time);
 */
