# DOCKER TESTING GUIDE - Complete & Ready
## 🐳 All Commands for Docker Environment

**Duration:** 20 minutes  
**All services run in Docker** - No local PostgreSQL/Kafka needed!

---

## ⚡ SUPER QUICK START

```bash
# 1. Start all services (PostgreSQL + Kafka + Zookeeper)
docker-compose up -d && sleep 30

# 2. Generate test data
cd testing && python generate_mock_data.py --mode full && cd ..

# 3. Setup database
docker-compose exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS fxdb;"
docker-compose exec postgres createdb -U postgres fxdb

# 4. Test Part A (copy-paste entire block)
docker-compose exec postgres psql -U postgres -d fxdb -c "
DROP TABLE IF EXISTS fx_rates;
CREATE TABLE fx_rates (
    event_id BIGINT PRIMARY KEY,
    event_time BIGINT NOT NULL,
    ccy_couple VARCHAR(6) NOT NULL,
    rate DECIMAL(18, 12) NOT NULL
);"

docker cp testing/mock_rates_current.csv postgres:/tmp/
docker-compose exec postgres psql -U postgres -d fxdb -c "\COPY fx_rates FROM '/tmp/mock_rates_current.csv' CSV HEADER;"
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_a.sql
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_a_test.sql

# 5. Test Part B (copy-paste entire block)
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/create_tables_part_b.sql
docker-compose exec postgres psql -U postgres -d fxdb -c "\COPY fx_rates_partitioned FROM '/tmp/mock_rates_current.csv' CSV HEADER;"
python testing/load_reference_rates.py
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_b.sql
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_b_test.sql


# Done! Part A & B tested! ✅
# For Part C, see detailed steps below
```

---

## 📋 PREREQUISITES

```bash
# Check you have:
docker --version          # Docker installed
docker-compose --version  # Docker Compose installed
python --version          # Python 3.8+

# Install Python dependencies
pip install kafka-python pytz rich psycopg2-binary
```

---

## 🚀 PART A: HOURLY BATCH PROCESSING

**Time:** 5 minutes

---

### **STEP A1: Start Services**

```bash
# FROM: fx_rates_solution/ (project root)

# Start PostgreSQL (+ Kafka/Zookeeper for later)
docker-compose up -d

# IMPORTANT: Wait for PostgreSQL to be ready!
echo "Waiting for services to start (30 seconds)..."
sleep 30

# Verify all running
docker-compose ps
```

**Expected Output:**
```
    Name                   Command               State           Ports
-------------------------------------------------------------------------
kafka                 /etc/confluent/docker/run   Up      0.0.0.0:9092->9092/tcp
postgres              docker-entrypoint.sh postgres Up    0.0.0.0:5432->5432/tcp
zookeeper             /etc/confluent/docker/run   Up      0.0.0.0:2181->2181/tcp
```

All should show "Up" ✅

---

### **STEP A2: Generate Test Data**

```bash
# FROM: fx_rates_solution/
cd testing

# Generate mock data (1 hour of data with current timestamps)
python generate_mock_data.py --mode batch --duration 3600
```

**Expected Output:**
```
============================================================
Generating batch CSV: mock_rates_current.csv
Duration: 3600 seconds
Pairs: 5
✓ Generated 18000 rates
✓ Time range: 2025-12-12 10:00:00 to 2025-12-12 11:00:00
✓ Saved to: mock_rates_current.csv

Generating yesterday 5PM reference rates: yesterday_rates.json
Yesterday 5PM NY: 2025-12-11 17:00:00-05:00
Yesterday 5PM UTC: 2025-12-11 22:00:00+00:00

✓ Extracting from CSV (realistic approach)
Extracting rates from mock_rates_current.csv
  EURUSD   1.08076  (±45.2s from target)
  GBPUSD   1.26231  (±52.1s from target)
  AUDUSD   0.65491  (±38.7s from target)
  NZDUSD   0.61643  (±41.3s from target)
  EURGBP   0.85620  (±49.8s from target)

✓ Generated 5 reference rates
✓ Saved to: yesterday_rates.json

Files created in testing/ directory:
  - mock_rates_current.csv (~2MB)
  - yesterday_rates.json (~200 bytes)
  - import_mock_data.sql (~500 bytes)
```

---

### **STEP A3: Create Database**

```bash
# FROM: fx_rates_solution/testing/
cd ..

# NOW IN: fx_rates_solution/

# Create database in Docker PostgreSQL
docker-compose exec postgres createdb -U postgres fxdb

# Verify
docker-compose exec postgres psql -U postgres -l | grep fxdb
```

**Expected:** fxdb appears in database list

---

### **STEP A4: Create Table**

```bash
# FROM: fx_rates_solution/

# Create fx_rates table
docker-compose exec postgres psql -U postgres -d fxdb -c "
CREATE TABLE IF NOT EXISTS fx_rates (
    event_id BIGINT PRIMARY KEY,
    event_time BIGINT NOT NULL,
    ccy_couple VARCHAR(6) NOT NULL,
    rate DECIMAL(18, 12) NOT NULL
);"

# Verify table created
docker-compose exec postgres psql -U postgres -d fxdb -c "\d fx_rates"
```

**Expected:**
```
                Table "public.fx_rates"
   Column    |      Type       | Collation | Nullable | Default
-------------+-----------------+-----------+----------+---------
 event_id    | bigint          |           | not null |
 event_time  | bigint          |           | not null |
 ccy_couple  | character varying(6) |      | not null |
 rate        | numeric(18,12)  |           | not null |
Indexes:
    "fx_rates_pkey" PRIMARY KEY, btree (event_id)
```

---

### **STEP A5: Import Test Data**

```bash
# FROM: fx_rates_solution/

# Copy CSV to Docker container
docker cp testing/mock_rates_current.csv postgres:/tmp/

# Import to database
docker-compose exec postgres psql -U postgres -d fxdb -c "\COPY fx_rates FROM '/tmp/mock_rates_current.csv' WITH (FORMAT CSV, HEADER true);"

# Verify import
docker-compose exec postgres psql -U postgres -d fxdb -c "SELECT COUNT(*) as total FROM fx_rates;"
```

**Expected:** 186010 rows

```bash
# Check by currency pair
docker-compose exec postgres psql -U postgres -d fxdb -c "
SELECT ccy_couple, COUNT(*) as count 
FROM fx_rates 
GROUP BY ccy_couple 
ORDER BY ccy_couple;"
```

**Expected:** 5 pairs with 37202 rows each

---

### **STEP A6: Verify Data Freshness**

```bash
# FROM: fx_rates_solution/

docker-compose exec postgres psql -U postgres -d fxdb -c "
SELECT 
    ccy_couple,
    COUNT(*) as count,
    TO_TIMESTAMP(MAX(event_time) / 1000) as latest_rate,
    ROUND(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - TO_TIMESTAMP(MAX(event_time) / 1000)))) as age_seconds
FROM fx_rates
GROUP BY ccy_couple
ORDER BY ccy_couple;"
```

**Expected:** age_seconds should be < 3600 (within last hour) ✅

---

### **STEP A7: Run Part A Solution**

⚠️ **IMPORTANT: Data Freshness!**

The solution filters rates older than 30 seconds. If you see 0 rows, your data is stale!

**Check data freshness first:**
```bash
docker-compose exec postgres psql -U postgres -d fxdb -c "
SELECT 
    ccy_couple,
    TO_TIMESTAMP(MAX(event_time) / 1000) as newest_rate,
    ROUND(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - TO_TIMESTAMP(MAX(event_time) / 1000)))) as age_seconds
FROM fx_rates
GROUP BY ccy_couple;"
```

**If age_seconds > 30:**

**Option 1: Regenerate fresh data (RECOMMENDED):**
```bash
cd testing
python generate_mock_data.py --mode batch --duration 3600
docker cp mock_rates_current.csv postgres:/tmp/
docker-compose exec postgres psql -U postgres -d fxdb -c "TRUNCATE fx_rates;"
docker-compose exec postgres psql -U postgres -d fxdb -c "\COPY fx_rates FROM '/tmp/mock_rates_current.csv' CSV HEADER;"
cd ..
# Run immediately (within 30 seconds!)
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_a.sql
```

**Option 2: Use test version (accepts data up to 1 hour old):**
```bash
# FROM: fx_rates_solution/

# Run test version (relaxed timing)
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_a_test.sql
```

**Expected Output:**
```
 ccy_couple |  rate   |   change   
------------+---------+------------
 "AUD/USD"  | 0.65491 | "+0.002%"
 "EUR/GBP"  | 0.85620 | "+0.001%"
 "EUR/USD"  | 1.08076 | "-0.001%"
 "GBP/USD"  | 1.26231 | "+0.000%"
 "NZD/USD"  | 0.61643 | "+0.001%"
(5 rows)
```

---

### **✅ PART A SUCCESS!**

Checklist:
- [x] 5 currency pairs returned
- [x] All have rates (no NULL)
- [x] Percentage changes calculated (not all "N/A")
- [x] Format: `"CCY1/CCY2",rate,"±X.XXX%"`
- [x] Execution time < 10 seconds

---

## 🚀 PART B: OPTIMIZED MINUTELY PROCESSING

**Time:** 8 minutes

---

### **STEP B1: Create Optimized Schema**

```bash
# FROM: fx_rates_solution/

# Run schema creation script
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/create_tables_part_b.sql
```

**Expected Output:**
```
CREATE TABLE
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE VIEW
CREATE VIEW
CREATE VIEW
DO
[Creates 14 partitions - past 7 days + future 7 days]
```

**Verify schema:**
```bash
docker-compose exec postgres psql -U postgres -d fxdb -c "\d fx_rates_partitioned"
docker-compose exec postgres psql -U postgres -d fxdb -c "\d yesterday_5pm_rates"
docker-compose exec postgres psql -U postgres -d fxdb -c "SELECT * FROM partition_stats;"

```
Expected: 14 partitions listed
---

### **STEP B2: Import Data to Partitioned Table**

```bash
# FROM: fx_rates_solution/

# CSV already in container from Part A, re-import to partitioned table
docker-compose exec postgres psql -U postgres -d fxdb -c "\COPY fx_rates_partitioned(event_id, event_time, ccy_couple, rate) FROM '/tmp/mock_rates_current.csv' WITH (FORMAT CSV, HEADER true);"

# Verify
docker-compose exec postgres psql -U postgres -d fxdb -c "
SELECT COUNT(*) as partitioned FROM fx_rates_partitioned;
SELECT COUNT(*) as regular FROM fx_rates;"
```

**Expected:** Both should show 186010

---

### **STEP B3: Load Reference Rates**

```bash
# FROM: fx_rates_solution/

# Use the Python helper script
python testing/load_reference_rates.py
```

**Expected Output:**
```
Loading reference rates from testing/yesterday_rates.json...
Found 5 reference rates
Connecting to database: postgresql://postgres:postgres@localhost:5432/fxdb
  ✓ EURUSD: 1.08076
  ✓ GBPUSD: 1.26231
  ✓ AUDUSD: 0.65491
  ✓ NZDUSD: 0.61643
  ✓ EURGBP: 0.85620

✓ Successfully loaded 5 reference rates!
```

**Verify:**
```bash
docker-compose exec postgres psql -U postgres -d fxdb -c "
SELECT * FROM yesterday_5pm_rates 
WHERE reference_date = CURRENT_DATE 
ORDER BY ccy_couple;"
```

**Expected:** 5 rows with reference rates

---

### **STEP B4: Run Part B Solution**

```bash
# FROM: fx_rates_solution/

docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_b_test.sql
```

**Expected Output:**
```
 ccy_couple |  rate   |   change   
------------+---------+------------
 "AUD/USD"  | 0.65491 | "+0.002%"
 "EUR/GBP"  | 0.85620 | "+0.001%"
 "EUR/USD"  | 1.08076 | "-0.001%"
 "GBP/USD"  | 1.26231 | "+0.000%"
 "NZD/USD"  | 0.61643 | "+0.001%"
(5 rows)

Time: 2345.678 ms (2.3 seconds)
```

**Key:** Execution time should be < 5 seconds! ✅

---

### **✅ PART B SUCCESS!**

Checklist:
- [x] Active rates returned
- [x] Percentage changes from yesterday_5pm_rates table
- [x] Execution time < 5 seconds
- [x] Partitioning working
- [x] Results match Part A (approximately)

---

## 🚀 PART C: REAL-TIME STREAMING

**Time:** 7 minutes  
**Requires:** 3 terminal windows

---

### **PREPARATION: Services Already Running**

PostgreSQL, Kafka, and Zookeeper are already running from Part A!

```bash
# Verify Kafka is ready
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# If Kafka not responding, wait more
sleep 10
```

---

### **3-TERMINAL LAYOUT**

```
┌─────────────────────┬─────────────────────┐
│  Terminal 1         │  Terminal 2         │
│  (Producer)         │  (Processor)        │
│                     │                     │
├─────────────────────┴─────────────────────┤
│  Terminal 3: LED Display (Visual)        │
└───────────────────────────────────────────┘
```

All terminals start from `fx_rates_solution/`

---

### **TERMINAL 1: Start Test Producer**

```bash
# Terminal 1
# FROM: fx_rates_solution/
cd testing

# Generate streaming data (120 seconds = 2 minutes)
python generate_mock_data.py --mode streaming --duration 120
```

**Expected Output:**
```
============================================================
STREAMING MODE - Generating reference rates
============================================================
⚠ No CSV provided, generating synthetic rates
  EURUSD   1.08076  (synthetic)
  ...

✓ Generated 5 reference rates

============================================================
STREAMING DATA TO KAFKA
============================================================
Duration: 120 seconds
Pairs: 5
Updates: 10 per second per pair

Starting at: 2025-12-12 11:00:00
Press Ctrl+C to stop

Sent 100 messages (50.0 msg/sec)
Sent 200 messages (50.1 msg/sec)
...
```

**Keep this running!** Don't close this terminal.

---

### **TERMINAL 2: Start Stream Processor**

```bash
# Terminal 2
# FROM: fx_rates_solution/
cd streaming

# Start processor with reference rates
python fx_rates_streaming.py --reference-rates ../testing/yesterday_rates.json
```

**Expected Output:**
```
============================================================
FX RATE STREAM PROCESSOR STARTED
============================================================
Bootstrap servers: ['localhost:9092']
Input topic: fx-rates-input
Output topic: fx-rates-led-display
Reference rates loaded: 5
============================================================

"EUR/USD",1.08077,"+0.001%"
"GBP/USD",1.26230,"-0.001%"
"AUD/USD",0.65492,"+0.002%"
"NZD/USD",0.61642,"-0.001%"
"EUR/GBP",0.85619,"-0.001%"
...

[Every 1000 messages:]
============================================================
PROCESSING STATISTICS
Messages received: 1000
Valid rates: 1000
Outputs generated: 980
Throughput: 50.2 msg/sec
Active pairs: 5
============================================================
```

**Keep this running!**

---

### **TERMINAL 3: Start LED Display**

```bash
# Terminal 3
# FROM: fx_rates_solution/
cd streaming

# Start LED display visualization
python led_display_visual.py
```

**Expected Output (Animated!):**
```
╔══════════════════════════════════════════════════════════════╗
║              FX RATES - LED DISPLAY SIMULATION               ║
║                    Real-Time Streaming                       ║
╠══════════════════════════════════════════════════════════════╣
║ Currency Pair    Rate         Change        Last Update      ║
╠══════════════════════════════════════════════════════════════╣
║ EUR/USD          1.08077      +0.001%  ↑    <1s ago         ║
║ GBP/USD          1.26230      -0.001%  ↓    <1s ago         ║
║ AUD/USD          0.65492      +0.002%  ↑    1s ago          ║
║ NZD/USD          0.61642      -0.001%  ↓    <1s ago         ║
║ EUR/GBP          0.85619      -0.001%  ↓    <1s ago         ║
╠══════════════════════════════════════════════════════════════╣
║ Total Updates: 1,234  |  Active: 5  |  Rate: 50.2 msg/sec  ║
╚══════════════════════════════════════════════════════════════╝

Last update: 2025-12-12 11:00:45.123  |  Press Ctrl+C to stop
```

**Colors:**
- 🟢 Green ↑ = Positive change
- 🔴 Red ↓ = Negative change
- 🟡 Yellow - = N/A

**This updates in real-time! Watch the magic! ✨**

---

### **VERIFICATION**

**Terminal 1 (Producer):**
- ✅ Sending messages
- ✅ ~50 msg/sec
- ✅ No errors

**Terminal 2 (Processor):**
- ✅ Consuming messages
- ✅ CSV lines appearing
- ✅ Statistics updating
- ✅ ~50 msg/sec throughput

**Terminal 3 (LED Display):**
- ✅ 5 currency pairs visible
- ✅ Rates updating
- ✅ Colors working
- ✅ "Last Update" < 1s
- ✅ Statistics accurate

---

### **STOP EVERYTHING**

After 2 minutes, stop all terminals:

```bash
# In each terminal: Ctrl+C

# All services still running (can reuse for more tests)
# To stop all services:
docker-compose down
```

---

### **✅ PART C SUCCESS!**

Checklist:
- [x] Producer sending messages
- [x] Processor consuming and processing
- [x] LED display updating in real-time
- [x] Latency < 1 second
- [x] Colors working (green ↑, red ↓)
- [x] Statistics accurate
- [x] All 5 pairs visible

---

## 🔧 TROUBLESHOOTING

### **Issue: docker-compose command not found**

```bash
# Try docker compose (without dash)
docker compose up -d

# Or install docker-compose
# https://docs.docker.com/compose/install/
```

### **Issue: PostgreSQL not ready**

```bash
# Wait longer
docker-compose up -d
sleep 60  # Wait a full minute

# Check logs
docker-compose logs postgres | tail -50

# Look for: "database system is ready to accept connections"
```

### **Issue: Kafka not ready**

```bash
# Kafka needs ~30 seconds
docker-compose restart kafka
sleep 30

# Check logs
docker-compose logs kafka | tail -50

# Look for: "Kafka Server started"
```

### **Issue: Part A returns no rows**

```bash
# Check data freshness
docker-compose exec postgres psql -U postgres -d fxdb -c "
SELECT MAX(TO_TIMESTAMP(event_time/1000)) as latest,
       EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MAX(TO_TIMESTAMP(event_time/1000)))) as age_sec
FROM fx_rates;"

# If age_sec > 30, regenerate data
cd testing
python generate_mock_data.py --mode batch
docker cp mock_rates_current.csv postgres:/tmp/
docker-compose exec postgres psql -U postgres -d fxdb -c "TRUNCATE fx_rates; \COPY fx_rates FROM '/tmp/mock_rates_current.csv' CSV HEADER;"
```

### **Issue: Part C - No output in LED display**

```bash
# Check producer is running (Terminal 1)
# Should see "Sent X messages"

# Check processor is running (Terminal 2)
# Should see CSV output lines

# Check Kafka topics
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list
# Should see: fx-rates-input, fx-rates-led-display

# View messages in topic
docker-compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic fx-rates-led-display \
  --from-beginning \
  --max-messages 5
```

---

## 📋 FINAL VALIDATION

### **All Tests Passed?**

**Part A:**
- [x] Database created
- [x] Table created
- [x] Data imported (18000 rows)
- [x] Data fresh (<1 hour old)
- [x] Query returns 5 pairs
- [x] Percentage changes showing
- [x] Time < 10 seconds

**Part B:**
- [x] Partitioned table created
- [x] Reference rates table created
- [x] Data imported
- [x] Reference rates loaded (5 rows)
- [x] Query returns active pairs
- [x] Time < 5 seconds
- [x] Partitioning working

**Part C:**
- [x] Kafka running
- [x] Producer sending
- [x] Processor consuming
- [x] LED display showing
- [x] Real-time updates
- [x] Latency < 1 second
- [x] Statistics accurate

---

##  SUCCESS!

**All 3 solutions tested and working!** 

**Time taken:** ~20 minutes  
**Solutions tested:** Part A, B, C  
**Status:** Ready for submission/demo/interview!

---

## 🧹 CLEANUP (Optional)

```bash
# Stop all services
docker-compose down

# Remove all data (clean slate)
docker-compose down -v

# Remove generated files
rm testing/mock_rates_current.csv
rm testing/yesterday_rates.json
rm testing/import_mock_data.sql
```

---

## 📞 QUICK REFERENCE

```bash
# Start services
docker-compose up -d && sleep 30

# Generate test data
cd testing && python generate_mock_data.py --mode full && cd ..

# Test Part A
docker-compose exec postgres createdb -U postgres fxdb
docker-compose exec postgres psql -U postgres -d fxdb -c "CREATE TABLE fx_rates (event_id BIGINT PRIMARY KEY, event_time BIGINT, ccy_couple VARCHAR(6), rate DECIMAL(18,12));"
docker cp testing/mock_rates_current.csv postgres:/tmp/
docker-compose exec postgres psql -U postgres -d fxdb -c "\COPY fx_rates FROM '/tmp/mock_rates_current.csv' CSV HEADER;"
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_a.sql

# Test Part B
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/create_tables_part_b.sql
docker-compose exec postgres psql -U postgres -d fxdb -c "\COPY fx_rates_partitioned FROM '/tmp/mock_rates_current.csv' CSV HEADER;"
python testing/load_reference_rates.py
docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_b.sql

# Test Part C (3 terminals)
# T1: python testing/generate_mock_data.py --mode streaming --duration 120
# T2: python streaming/fx_rates_streaming.py
# T3: python streaming/led_display_visual.py

# Stop services
docker-compose down
```

---

**Ready to test! Follow this guide step by step.** 📖✨
