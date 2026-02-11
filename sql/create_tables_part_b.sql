/*
 * OPTIMIZED TABLE DEFINITIONS FOR PART B - FINAL VERSION
 * 
 * This script creates the optimized table structures needed for high-frequency
 * minutely processing of 300 currency pairs.
 * 
 * Key Features:
 * - Time-based partitioning for efficient data pruning
 * - Composite indexes for fast lookups
 * - Regular table for yesterday's reference rates (not materialized view)
 * - Pure SQL (no PL/pgSQL functions required)
 * - Automatic partition creation for 14 days (past 7 + future 7)
 * 
 * IMPORTANT: This version uses PURE SQL only!
 * No stored procedures or functions required.
 * Everything can be run as standard SQL statements.
 */

-- ============================================================================
-- 1. MAIN RATES TABLE (Partitioned by Time)
-- ============================================================================

-- Drop existing table if recreating
DROP TABLE IF EXISTS fx_rates_partitioned CASCADE;

-- Create partitioned table
CREATE TABLE fx_rates_partitioned (
    event_id BIGINT NOT NULL,
    event_time BIGINT NOT NULL,
    ccy_couple VARCHAR(6) NOT NULL,
    rate DOUBLE PRECISION NOT NULL,
    
    -- Constraints
    CHECK (rate >= 0),
    CHECK (LENGTH(ccy_couple) = 6),
    CHECK (event_time > 0)
    
) PARTITION BY RANGE (event_time);

-- ============================================================================
-- 2. CREATE PARTITIONS AUTOMATICALLY
-- ============================================================================
-- This block creates partitions for the last 7 days and next 7 days
-- Ensures we always have partitions for current data

DO $$
DECLARE
    start_date DATE;
    end_date DATE;
    partition_start BIGINT;
    partition_end BIGINT;
    partition_name TEXT;
BEGIN
    -- Loop: Create partitions for last 7 days and next 7 days
    FOR i IN -7..7 LOOP
        start_date := CURRENT_DATE + (i || ' days')::INTERVAL;
        end_date := start_date + INTERVAL '1 day';
        
        -- Convert dates to epoch milliseconds
        partition_start := EXTRACT(EPOCH FROM start_date)::BIGINT * 1000;
        partition_end := EXTRACT(EPOCH FROM end_date)::BIGINT * 1000;
        
        -- Generate partition name (e.g., fx_rates_2024_12_10)
        partition_name := 'fx_rates_' || TO_CHAR(start_date, 'YYYY_MM_DD');
        
        -- Create partition
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF fx_rates_partitioned
             FOR VALUES FROM (%L) TO (%L)',
            partition_name, partition_start, partition_end
        );
        
        -- Create index on (ccy_couple, event_time DESC) for each partition
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (ccy_couple, event_time DESC)',
            partition_name || '_ccy_time_idx', partition_name
        );
        
        -- Create index on event_time for fast time-based filtering
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (event_time DESC)',
            partition_name || '_time_idx', partition_name
        );
    END LOOP;
    
    RAISE NOTICE 'Created partitions from % to %', 
                 TO_CHAR(CURRENT_DATE - INTERVAL '7 days', 'YYYY-MM-DD'),
                 TO_CHAR(CURRENT_DATE + INTERVAL '7 days', 'YYYY-MM-DD');
END $$;

-- Create primary key (automatically creates unique index)
-- Note: Primary key must include partition key (event_time)
ALTER TABLE fx_rates_partitioned 
ADD CONSTRAINT fx_rates_partitioned_pkey 
PRIMARY KEY (event_id, event_time);

COMMENT ON TABLE fx_rates_partitioned IS 
'Main FX rates table, partitioned by event_time for efficient querying. 
Each partition covers one day. Old partitions can be dropped to manage storage.';

-- ============================================================================
-- 3. YESTERDAY''S 5PM REFERENCE RATES TABLE
-- ============================================================================
-- This table stores pre-computed rates for yesterday's 5PM NY time
-- Updated daily by running update_yesterday_rates_final.sql

DROP TABLE IF EXISTS yesterday_5pm_rates CASCADE;

CREATE TABLE yesterday_5pm_rates (
    ccy_couple VARCHAR(6) NOT NULL,
    rate DOUBLE PRECISION NOT NULL,
    reference_date DATE NOT NULL,  -- The date this represents "yesterday" for (i.e., today's date)
    snapshot_time TIMESTAMP NOT NULL,  -- Actual timestamp of the rate
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    PRIMARY KEY (ccy_couple, reference_date),
    CHECK (rate > 0),
    CHECK (LENGTH(ccy_couple) = 6)
);

-- Index for fast lookups during minutely queries
CREATE INDEX idx_yesterday_rates_date 
ON yesterday_5pm_rates (reference_date);

COMMENT ON TABLE yesterday_5pm_rates IS 
'Pre-computed reference rates from yesterday 5PM NY time. 
Updated daily at 5PM NY by running update_yesterday_rates_final.sql.
Stores 7 days of history for debugging and historical queries.';

COMMENT ON COLUMN yesterday_5pm_rates.reference_date IS 
'The date this represents "yesterday" for. 
Example: If today is 2024-12-11, this contains yesterday (2024-12-10) 5PM rates.';

COMMENT ON COLUMN yesterday_5pm_rates.snapshot_time IS 
'The actual timestamp of the rate (at or before 5PM NY on the reference date).';

-- ============================================================================
-- 4. ADDITIONAL INDEXES FOR PERFORMANCE
-- ============================================================================

-- Composite index on main table for efficient currency-specific queries
CREATE INDEX idx_rates_ccy_couple 
ON ONLY fx_rates_partitioned (ccy_couple) 
WHERE rate > 0;

-- Index for rate validity filtering (helps with WHERE rate > 0)
CREATE INDEX idx_rates_valid 
ON ONLY fx_rates_partitioned (event_time DESC) 
WHERE rate > 0;

COMMENT ON INDEX idx_rates_ccy_couple IS 
'Index for filtering by currency pair. Used when querying specific pairs.';

COMMENT ON INDEX idx_rates_valid IS 
'Index for filtering valid rates only. Helps performance when excluding zero rates.';

-- ============================================================================
-- 5. UTILITY VIEWS FOR MONITORING
-- ============================================================================

-- View to check partition sizes and row counts
CREATE OR REPLACE VIEW partition_stats AS
SELECT 
    schemaname,
    relname AS tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname)) AS size,
    n_live_tup AS row_count,
    n_dead_tup AS dead_rows,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze
FROM pg_stat_user_tables
WHERE relname LIKE 'fx_rates_%' OR relname = 'yesterday_5pm_rates'
ORDER BY relname DESC;

COMMENT ON VIEW partition_stats IS 
'Monitoring view showing size, row counts, and vacuum statistics for all partitions.
Use this to identify bloat and determine when maintenance is needed.';

-- View to check yesterday rates coverage
CREATE OR REPLACE VIEW yesterday_rates_coverage AS
SELECT 
    reference_date,
    COUNT(DISTINCT ccy_couple) AS currency_pairs,
    MIN(snapshot_time) AS earliest_snapshot,
    MAX(snapshot_time) AS latest_snapshot,
    MIN(rate) AS min_rate,
    MAX(rate) AS max_rate,
    ROUND(AVG(rate)::NUMERIC, 5) AS avg_rate
FROM yesterday_5pm_rates
GROUP BY reference_date
ORDER BY reference_date DESC;

COMMENT ON VIEW yesterday_rates_coverage IS 
'Summary view of reference rates by date.
Shows coverage (how many pairs have reference rates) and basic statistics.
Use this to verify daily refresh job is working correctly.';

-- View to check index usage
CREATE OR REPLACE VIEW index_usage AS
SELECT 
    schemaname,
    relname AS tablename,
    indexrelname AS indexname,
    idx_scan AS index_scans,
    idx_tup_read AS tuples_read,
    idx_tup_fetch AS tuples_fetched,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE relname LIKE 'fx_rates%' OR relname = 'yesterday_5pm_rates'
ORDER BY idx_scan DESC;

COMMENT ON VIEW index_usage IS 
'Shows how often each index is used and how much space it consumes.
Indexes with zero scans may be candidates for removal.';

-- ============================================================================
-- 6. TABLE STATISTICS AND MAINTENANCE SETTINGS
-- ============================================================================

-- Update table statistics for query planner
ANALYZE fx_rates_partitioned;
ANALYZE yesterday_5pm_rates;

-- Note: Autovacuum settings commented out for compatibility
-- Uncomment if your PostgreSQL version supports these parameters (10+)
/*
-- Set autovacuum parameters for high-write tables
-- More aggressive than default because we have high update frequency
ALTER TABLE fx_rates_partitioned SET (
    autovacuum_vacuum_scale_factor = 0.05,  -- Vacuum when 5% of rows are dead (vs 20% default)
    autovacuum_analyze_scale_factor = 0.02  -- Analyze when 2% changed (vs 10% default)
);

ALTER TABLE yesterday_5pm_rates SET (
    autovacuum_vacuum_scale_factor = 0.1,   -- Less frequent (low update volume)
    autovacuum_analyze_scale_factor = 0.05
);
*/

-- ============================================================================
-- 7. SETUP VERIFICATION QUERIES
-- ============================================================================

-- Verify tables were created
SELECT 
    'Table created:' AS status,
    tablename, 
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables 
WHERE schemaname = 'public' 
    AND (tablename LIKE 'fx_rates%' OR tablename = 'yesterday_5pm_rates')
ORDER BY tablename;

-- Verify partitions were created
SELECT 
    'Partition created:' AS status,
    child.relname AS partition_name,
    pg_size_pretty(pg_relation_size(child.oid)) AS size
FROM pg_inherits
JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
JOIN pg_class child ON pg_inherits.inhrelid = child.oid
WHERE parent.relname = 'fx_rates_partitioned'
ORDER BY child.relname;

-- Verify indexes were created
SELECT 
    'Index created:' AS status,
    schemaname,
    tablename,
    indexname
FROM pg_indexes
WHERE tablename LIKE 'fx_rates%' OR tablename = 'yesterday_5pm_rates'
ORDER BY tablename, indexname;

/*
 * ============================================================================
 * MANUAL PARTITION MANAGEMENT (If needed)
 * ============================================================================
 * 
 * The DO block above creates 14 days of partitions automatically.
 * For ongoing production use, you should automate partition management.
 * 
 * OPTION 1: Scheduled SQL (via cron or pg_cron)
 * Run this daily to create tomorrow's partition:
 */

-- Example: Create partition for tomorrow
-- Run this query daily at midnight

/*
DO $$
DECLARE
    tomorrow_date DATE := CURRENT_DATE + INTERVAL '1 day';
    partition_start BIGINT := EXTRACT(EPOCH FROM tomorrow_date)::BIGINT * 1000;
    partition_end BIGINT := EXTRACT(EPOCH FROM (tomorrow_date + INTERVAL '1 day'))::BIGINT * 1000;
    partition_name TEXT := 'fx_rates_' || TO_CHAR(tomorrow_date, 'YYYY_MM_DD');
BEGIN
    -- Create partition if it doesn't exist
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF fx_rates_partitioned
         FOR VALUES FROM (%L) TO (%L)',
        partition_name, partition_start, partition_end
    );
    
    -- Create indexes
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS %I ON %I (ccy_couple, event_time DESC)',
        partition_name || '_ccy_time_idx', partition_name
    );
    
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS %I ON %I (event_time DESC)',
        partition_name || '_time_idx', partition_name
    );
    
    RAISE NOTICE 'Created partition for %', tomorrow_date;
END $$;
*/

/*
 * Drop old partitions (keep last 7 days):
 * Run this daily to clean up
 */

/*
DO $$
DECLARE
    old_date DATE := CURRENT_DATE - INTERVAL '8 days';
    partition_name TEXT := 'fx_rates_' || TO_CHAR(old_date, 'YYYY_MM_DD');
BEGIN
    EXECUTE format('DROP TABLE IF EXISTS %I', partition_name);
    RAISE NOTICE 'Dropped partition for %', old_date;
END $$;
*/

/*
 * OPTION 2: Use pg_partman extension (recommended for production)
 * 
 * 1. Install extension:
 *    CREATE EXTENSION pg_partman;
 * 
 * 2. Configure automatic partition management:
 *    SELECT partman.create_parent(
 *        p_parent_table => 'public.fx_rates_partitioned',
 *        p_control => 'event_time',
 *        p_type => 'native',
 *        p_interval => 'daily',
 *        p_premake => 7
 *    );
 * 
 * 3. Schedule maintenance:
 *    SELECT cron.schedule('partman-maintenance', '0 * * * *', 
 *        $$CALL partman.run_maintenance_proc()$$);
 */

/*
 * ============================================================================
 * DATA MIGRATION (If migrating from Part A schema)
 * ============================================================================
 * 
 * If you have existing data in fx_rates table from Part A:
 */

/*
-- Step 1: Copy data to new partitioned table
INSERT INTO fx_rates_partitioned (event_id, event_time, ccy_couple, rate)
SELECT event_id, event_time, ccy_couple, rate
FROM fx_rates
WHERE rate > 0;

-- Step 2: Verify row counts match
SELECT 'Old table:' AS source, COUNT(*) FROM fx_rates WHERE rate > 0
UNION ALL
SELECT 'New table:' AS source, COUNT(*) FROM fx_rates_partitioned;

-- Step 3: Rename tables (once verified)
ALTER TABLE fx_rates RENAME TO fx_rates_old_backup;
-- Note: We keep fx_rates_partitioned name as-is since queries reference it
*/

/*
 * ============================================================================
 * MAINTENANCE SCHEDULE (Production Recommendations)
 * ============================================================================
 * 
 * DAILY TASKS:
 * ----------------
 * 00:00 UTC - Create tomorrow's partition (see manual partition mgmt above)
 * 00:05 UTC - Drop old partitions (keep 7 days)
 * 02:00 UTC - VACUUM ANALYZE fx_rates_partitioned
 * 17:00 EST - Run update_yesterday_rates_final.sql (refresh reference rates)
 * 
 * WEEKLY TASKS:
 * ----------------
 * - Review partition_stats view (check for bloat)
 * - Review index_usage view (identify unused indexes)
 * - Review yesterday_rates_coverage (verify data completeness)
 * - Check query performance logs
 * 
 * MONTHLY TASKS:
 * ----------------
 * - Review and analyze slow queries (EXPLAIN ANALYZE)
 * - Adjust autovacuum settings if needed
 * - Archive very old partitions to cold storage
 * - Review and update statistics targets
 * 
 * EXAMPLE CRON SCHEDULE:
 * 
 * # Create tomorrow's partition
 * 0 0 * * * psql -d fxdb -f /path/to/create_tomorrow_partition.sql
 * 
 * # Drop old partitions
 * 5 0 * * * psql -d fxdb -f /path/to/drop_old_partitions.sql
 * 
 * # Daily vacuum
 * 0 2 * * * psql -d fxdb -c "VACUUM ANALYZE fx_rates_partitioned;"
 * 
 * # Refresh reference rates (5PM NY = adjust for your timezone)
 * 0 17 * * * TZ=America/New_York psql -d fxdb -f /path/to/update_yesterday_rates_final.sql
 */

/*
 * ============================================================================
 * PERFORMANCE TUNING RECOMMENDATIONS
 * ============================================================================
 * 
 * PostgreSQL Configuration (postgresql.conf):
 * 
 * # Memory settings (adjust based on available RAM)
 * shared_buffers = 2GB              # 25% of RAM for dedicated server
 * effective_cache_size = 6GB        # 75% of RAM
 * work_mem = 64MB                   # Per-query working memory
 * maintenance_work_mem = 512MB      # For VACUUM, CREATE INDEX
 * 
 * # Query optimization
 * random_page_cost = 1.1            # Lower for SSD (default 4.0 for HDD)
 * effective_io_concurrency = 200    # Higher for SSD (default 1)
 * 
 * # Parallel execution
 * max_parallel_workers_per_gather = 4
 * max_parallel_workers = 8
 * max_worker_processes = 8
 * 
 * # Partitioning
 * enable_partition_pruning = on     # Essential for performance
 * constraint_exclusion = partition  # Helps partition pruning
 * 
 * # Autovacuum (already set per-table above, but global settings matter too)
 * autovacuum = on
 * autovacuum_max_workers = 3
 * autovacuum_naptime = 10s          # More frequent checks
 */

-- ============================================================================
-- SETUP COMPLETE!
-- ============================================================================

-- Next steps:
-- 1. Load sample data (if testing):
--    \COPY fx_rates_partitioned FROM '/rates_sample.csv' WITH (FORMAT CSV, HEADER true);
--
-- 2. Initialize reference rates:
--    Run update_yesterday_rates.sql
--
-- 3. Test main query:
--    Run solution_part_b.sql
--
-- 4. Schedule jobs:
--    - Minutely: solution_part_b.sql
--    - Daily: update_yesterday_rates.sql (5PM NY)
--    - Daily: partition management (midnight)
--
-- 5. Monitor performance:
--    SELECT * FROM partition_stats;
--    SELECT * FROM yesterday_rates_coverage;
--    SELECT * FROM index_usage;
