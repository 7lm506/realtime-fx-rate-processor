#!/usr/bin/env python3
"""
MOCK DATA GENERATOR WITH YESTERDAY + CURRENT TIMESTAMPS
========================================================

Generates realistic FX rate data with BOTH:
1. Yesterday 5PM data (for SQL reference rates)
2. Current timestamps (for active rates)

Perfect for testing Part A, B, and C solutions.

Usage:
    # Generate everything (recommended)
    python generate_mock_data.py --mode full
    
    # Generate CSV for batch (Part A/B)
    python generate_mock_data.py --mode batch --duration 3600
    
    # Stream to Kafka (Part C)
    python generate_mock_data.py --mode streaming --duration 60
"""

import csv
import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytz

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Mock data configuration"""
    
    # Currency pairs with realistic starting rates
    CURRENCY_PAIRS = {
        'EURUSD': 1.08077,
        'GBPUSD': 1.26230,
        'AUDUSD': 0.65490,
        'NZDUSD': 0.61642,
        'EURGBP': 0.85619
    }
    
    # Market volatility (realistic)
    VOLATILITY = 0.0001  # 0.01% per update
    
    # Update frequency
    UPDATES_PER_SECOND = 10  # Per currency pair
    
    # Timezone
    NY_TZ = pytz.timezone('America/New_York')


# ============================================================================
# BATCH MODE: Generate CSV with YESTERDAY + CURRENT Timestamps
# ============================================================================

def generate_batch_csv(output_file: str = 'mock_rates_current.csv', duration_seconds: int = 3600):
    """
    Generate CSV file with TWO time windows:
    1. Yesterday 5PM ±10 minutes (for reference rates)
    2. Recent data (NOW - duration to NOW)
    
    This ensures SQL queries can find BOTH:
    - Yesterday 5PM reference rates
    - Current active rates
    
    Args:
        output_file: Output CSV filename
        duration_seconds: How much recent historical data to generate
    """
    print(f"\n{'='*60}")
    print(f"GENERATING BATCH CSV WITH YESTERDAY + CURRENT DATA")
    print(f"{'='*60}")
    
    # Calculate yesterday 5PM
    now_ny = datetime.now(Config.NY_TZ)
    yesterday = now_ny.date() - timedelta(days=1)
    yesterday_5pm = datetime.combine(yesterday, datetime.min.time().replace(hour=17))
    yesterday_5pm_ny = Config.NY_TZ.localize(yesterday_5pm)
    yesterday_5pm_utc = yesterday_5pm_ny.astimezone(pytz.UTC)
    yesterday_5pm_ts = yesterday_5pm_utc.timestamp()
    
    print(f"\nYesterday 5PM NY: {yesterday_5pm_ny}")
    print(f"Yesterday 5PM UTC: {yesterday_5pm_utc}")
    print(f"Recent window: {duration_seconds} seconds")
    
    rates = []
    event_id = 1000000000000
    
    # ========================================================================
    # WINDOW 1: Yesterday 5PM (±10 minutes)
    # ========================================================================
    print(f"\n[1/2] Generating yesterday 5PM window (±10 minutes)...")
    
    yesterday_start = yesterday_5pm_ts - 600  # 10 min before
    yesterday_end = yesterday_5pm_ts + 600    # 10 min after
    current_time = yesterday_start
    current_rates = Config.CURRENCY_PAIRS.copy()
    
    while current_time <= yesterday_end:
        for ccy, base_rate in current_rates.items():
            # Very small movement (stable around base rate)
            change = random.gauss(0, base_rate * 0.0001)
            new_rate = max(0.0001, base_rate + change)
            current_rates[ccy] = new_rate
            
            event_id += 1
            rates.append({
                'event_id': event_id,
                'event_time': int(current_time * 1000),
                'ccy_couple': ccy,
                'rate': round(new_rate, 15)
            })
        
        current_time += 1.0  # 1 Hz
    
    yesterday_count = len(rates)
    print(f"✓ Generated {yesterday_count} rates around yesterday 5PM")
    
    # ========================================================================
    # WINDOW 2: Recent data (NOW - duration to NOW)
    # ========================================================================
    print(f"\n[2/2] Generating recent window (last {duration_seconds} seconds)...")
    
    end_time = time.time()
    start_time = end_time - duration_seconds
    current_time = start_time
    current_rates = Config.CURRENCY_PAIRS.copy()
    update_interval = 1.0 / Config.UPDATES_PER_SECOND
    
    while current_time <= end_time:
        for ccy, base_rate in current_rates.items():
            # Normal market movement
            change = random.gauss(0, base_rate * Config.VOLATILITY)
            new_rate = max(0.0001, base_rate + change)
            current_rates[ccy] = new_rate
            
            event_id += 1
            rates.append({
                'event_id': event_id,
                'event_time': int(current_time * 1000),
                'ccy_couple': ccy,
                'rate': round(new_rate, 15)
            })
        
        current_time += update_interval
    
    recent_count = len(rates) - yesterday_count
    print(f"✓ Generated {recent_count} rates for recent window")
    
    # Write to CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['event_id', 'event_time', 'ccy_couple', 'rate'])
        writer.writeheader()
        writer.writerows(rates)
    
    print(f"\n{'='*60}")
    print(f"✓ TOTAL: {len(rates)} rates")
    print(f"✓ Yesterday window: {yesterday_count} rates")
    print(f"✓ Recent window: {recent_count} rates")
    print(f"✓ Time ranges:")
    print(f"   - Yesterday: {datetime.fromtimestamp(yesterday_start)} to {datetime.fromtimestamp(yesterday_end)}")
    print(f"   - Recent: {datetime.fromtimestamp(start_time)} to {datetime.fromtimestamp(end_time)}")
    print(f"✓ Saved to: {output_file}")
    print(f"{'='*60}")
    
    return output_file


# ============================================================================
# EXTRACT YESTERDAY RATES FROM CSV
# ============================================================================

def extract_rates_from_csv(csv_file: str, target_timestamp_ms: int) -> dict:
    """
    Extract rates closest to target timestamp from CSV.
    This mimics the SQL query behavior in Part A/B.
    
    Args:
        csv_file: Path to CSV file with rate data
        target_timestamp_ms: Target timestamp in epoch milliseconds
        
    Returns:
        Dictionary of {ccy_couple: rate}
    """
    print(f"Extracting rates from {csv_file} at timestamp {target_timestamp_ms}")
    
    reference_rates = {}
    
    # Read CSV and find closest rate for each currency
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        
        # Group by currency
        rates_by_ccy = {}
        for row in reader:
            ccy = row['ccy_couple']
            event_time = int(row['event_time'])
            rate = float(row['rate'])
            
            if ccy not in rates_by_ccy:
                rates_by_ccy[ccy] = []
            rates_by_ccy[ccy].append((event_time, rate))
    
    # Find closest rate for each currency
    for ccy, rates in rates_by_ccy.items():
        # Sort by time difference from target
        closest = min(rates, key=lambda x: abs(x[0] - target_timestamp_ms))
        reference_rates[ccy] = closest[1]
        
        time_diff_seconds = abs(closest[0] - target_timestamp_ms) / 1000
        print(f"  {ccy:8s} {closest[1]:.5f}  (±{time_diff_seconds:.1f}s from target)")
    
    return reference_rates


# ============================================================================
# YESTERDAY 5PM RATES: Generate Reference Rates
# ============================================================================

def generate_yesterday_5pm_rates(csv_file: str = None, output_file: str = 'yesterday_rates.json'):
    """
    Generate yesterday's 5PM NY reference rates.
    
    Strategy:
    - If csv_file provided: Extract from CSV (realistic, consistent with batch data)
    - If csv_file is None: Generate synthetic (for streaming-only testing)
    
    Args:
        csv_file: Optional CSV file to extract rates from
        output_file: Output JSON filename
    """
    print(f"\n{'='*60}")
    print(f"GENERATING YESTERDAY 5PM REFERENCE RATES")
    print(f"{'='*60}")
    
    # Calculate yesterday 5PM NY in UTC
    now_ny = datetime.now(Config.NY_TZ)
    yesterday = now_ny.date() - timedelta(days=1)
    yesterday_5pm = datetime.combine(yesterday, datetime.min.time().replace(hour=17))
    yesterday_5pm_ny = Config.NY_TZ.localize(yesterday_5pm)
    yesterday_5pm_utc = yesterday_5pm_ny.astimezone(pytz.UTC)
    yesterday_5pm_ms = int(yesterday_5pm_utc.timestamp() * 1000)
    
    print(f"\nYesterday 5PM NY: {yesterday_5pm_ny}")
    print(f"Yesterday 5PM UTC: {yesterday_5pm_utc}")
    
    # Extract or generate reference rates
    if csv_file and Path(csv_file).exists():
        print(f"\n✓ Extracting from CSV (realistic approach)")
        reference_rates = extract_rates_from_csv(csv_file, yesterday_5pm_ms)
    else:
        print(f"\n⚠ No CSV provided, generating synthetic rates")
        print(f"  (For production-like testing, provide csv_file parameter)")
        
        # Generate synthetic reference rates
        reference_rates = {}
        for ccy_couple, current_rate in Config.CURRENCY_PAIRS.items():
            # Add small random change (-0.1% to +0.1%)
            change_pct = random.uniform(-0.001, 0.001)
            yesterday_rate = current_rate * (1 + change_pct)
            reference_rates[ccy_couple] = round(yesterday_rate, 15)
            print(f"  {ccy_couple:8s} {yesterday_rate:.5f}  (synthetic)")
    
    # Write to JSON
    with open(output_file, 'w') as f:
        json.dump(reference_rates, f, indent=2)
    
    print(f"\n✓ Generated {len(reference_rates)} reference rates")
    print(f"✓ Saved to: {output_file}")
    
    # Show comparison with current rates
    print("\nReference vs Current rates:")
    for ccy, ref_rate in reference_rates.items():
        if ccy in Config.CURRENCY_PAIRS:
            current = Config.CURRENCY_PAIRS[ccy]
            change = ((current - ref_rate) / ref_rate) * 100
            print(f"  {ccy:8s} Ref: {ref_rate:.5f}  Curr: {current:.5f}  Change: {change:+.3f}%")
    
    print(f"{'='*60}")
    
    return reference_rates


# ============================================================================
# STREAMING MODE: Generate to Kafka with Current Timestamps
# ============================================================================

def generate_streaming_kafka(duration_seconds: int = 60):
    """
    Generate streaming data directly to Kafka with current timestamps.
    Perfect for testing Part C.
    
    Args:
        duration_seconds: How long to generate data
    """
    try:
        from kafka import KafkaProducer
    except ImportError:
        print("ERROR: kafka-python not installed")
        print("Run: pip install kafka-python")
        return
    
    print(f"\n{'='*60}")
    print(f"STREAMING DATA TO KAFKA")
    print(f"{'='*60}")
    print(f"Duration: {duration_seconds} seconds")
    print(f"Pairs: {len(Config.CURRENCY_PAIRS)}")
    print(f"Updates: {Config.UPDATES_PER_SECOND} per second per pair")
    
    # Initialize producer
    producer = KafkaProducer(
        bootstrap_servers=['localhost:9092'],
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    
    current_rates = Config.CURRENCY_PAIRS.copy()
    event_id = 1000000000000
    
    start_time = time.time()
    end_time = start_time + duration_seconds
    
    messages_sent = 0
    update_interval = 1.0 / Config.UPDATES_PER_SECOND
    
    print(f"\nStarting at: {datetime.now()}")
    print("Press Ctrl+C to stop\n")
    
    try:
        while time.time() < end_time:
            for ccy_couple, base_rate in current_rates.items():
                # Simulate market movement
                change = random.gauss(0, base_rate * Config.VOLATILITY)
                new_rate = max(0.0001, base_rate + change)
                current_rates[ccy_couple] = new_rate
                
                # Create rate event with CURRENT timestamp
                event_id += 1
                rate_data = {
                    'event_id': event_id,
                    'event_time': int(time.time() * 1000),  # NOW!
                    'ccy_couple': ccy_couple,
                    'rate': round(new_rate, 15)
                }
                
                # Send to Kafka
                producer.send('fx-rates-input', value=rate_data)
                messages_sent += 1
                
                # Log progress
                if messages_sent % 100 == 0:
                    elapsed = time.time() - start_time
                    rate = messages_sent / elapsed if elapsed > 0 else 0
                    print(f"Sent {messages_sent} messages ({rate:.1f} msg/sec)")
            
            # Sleep until next update
            time.sleep(update_interval)
    
    except KeyboardInterrupt:
        print("\nStopped by user")
    
    finally:
        producer.flush()
        producer.close()
        
        elapsed = time.time() - start_time
        print(f"\n✓ Sent {messages_sent} messages in {elapsed:.1f} seconds")
        print(f"✓ Average rate: {messages_sent/elapsed:.1f} msg/sec")


# ============================================================================
# FULL TEST SETUP: Generate Everything
# ============================================================================

def generate_full_test_setup():
    """
    Generate complete test setup:
    - Batch CSV with yesterday + current timestamps
    - Yesterday reference rates (extracted from CSV)
    - SQL import script
    """
    print("=" * 60)
    print("GENERATING COMPLETE TEST SETUP")
    print("=" * 60)
    
    # 1. Generate batch CSV (with yesterday + recent data)
    csv_filename = 'mock_rates_current.csv'
    generate_batch_csv(csv_filename, duration_seconds=3600)
    
    # 2. Extract yesterday 5PM reference rates FROM the CSV we just generated
    # This mimics the SQL query behavior and ensures consistency
    reference_rates = generate_yesterday_5pm_rates(
        csv_file=csv_filename,
        output_file='yesterday_rates.json'
    )
    
    # 3. Print instructions
    print("\n" + "=" * 60)
    print("TEST SETUP COMPLETE!")
    print("=" * 60)
    
    print("\n📝 FILES CREATED:")
    print("  - mock_rates_current.csv (batch data with 2 time windows)")
    print("  - yesterday_rates.json (reference rates extracted from CSV)")
    print("  - import_mock_data.sql (SQL import script)")
    
    print("\n📝 HOW TO TEST:")
    print("\n1. TEST PART A (Hourly Batch):")
    print("   docker cp testing/mock_rates_current.csv postgres:/tmp/")
    print("   docker-compose exec postgres psql -U postgres -d fxdb -c \"\\COPY fx_rates FROM '/tmp/mock_rates_current.csv' CSV HEADER;\"")
    print("   docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_a.sql")
    
    print("\n2. TEST PART B (Minutely Batch):")
    print("   docker-compose exec postgres psql -U postgres -d fxdb -c \"\\COPY fx_rates_partitioned FROM '/tmp/mock_rates_current.csv' CSV HEADER;\"")
    print("   python testing/load_reference_rates.py")
    print("   docker-compose exec -T postgres psql -U postgres -d fxdb < sql/solution_part_b.sql")
    
    print("\n3. TEST PART C (Streaming):")
    print("   # Terminal 1: docker-compose up -d")
    print("   # Terminal 2: python testing/generate_mock_data.py --mode streaming --duration 120")
    print("   # Terminal 3: python streaming/fx_rates_streaming.py")
    print("   # Terminal 4: python streaming/led_display_visual.py")
    
    print("\n✅ All files generated successfully!")


# ============================================================================
# SQL IMPORT HELPER
# ============================================================================

def generate_sql_import_script(csv_file: str, output_file: str = 'import_mock_data.sql'):
    """
    Generate SQL script to import mock CSV data.
    
    Args:
        csv_file: Input CSV file
        output_file: Output SQL script
    """
    print(f"\nGenerating SQL import script: {output_file}")
    
    sql_script = f"""-- SQL SCRIPT TO IMPORT MOCK DATA
-- Generated: {datetime.now()}
-- Source: {csv_file}

-- For Part A (simple table)
\\COPY fx_rates(event_id, event_time, ccy_couple, rate) 
FROM '{csv_file}' 
WITH (FORMAT CSV, HEADER true);

-- Verify import
SELECT COUNT(*) as total_rows FROM fx_rates;
SELECT ccy_couple, COUNT(*) as count FROM fx_rates GROUP BY ccy_couple;

-- Show sample data
SELECT * FROM fx_rates ORDER BY event_time DESC LIMIT 10;
"""
    
    with open(output_file, 'w') as f:
        f.write(sql_script)
    
    print(f"✓ Generated SQL import script: {output_file}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Generate mock FX rate data with yesterday + current timestamps',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate complete test setup (recommended)
  python generate_mock_data.py --mode full
  
  # Generate batch CSV only
  python generate_mock_data.py --mode batch --duration 3600
  
  # Generate yesterday reference rates
  python generate_mock_data.py --mode reference
  
  # Stream to Kafka for 60 seconds
  python generate_mock_data.py --mode streaming --duration 60
        """
    )
    
    parser.add_argument(
        '--mode',
        choices=['full', 'batch', 'reference', 'streaming'],
        default='full',
        help='Generation mode (default: full)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='mock_rates_current.csv',
        help='Output CSV filename for batch mode'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=3600,
        help='Duration in seconds for recent window (default: 3600 = 1 hour)'
    )
    
    args = parser.parse_args()
    
    if args.mode == 'full':
        generate_full_test_setup()
        generate_sql_import_script('mock_rates_current.csv')
    
    elif args.mode == 'batch':
        csv_file = generate_batch_csv(args.output, args.duration)
        # Also generate reference rates from this CSV
        print("\n" + "=" * 60)
        generate_yesterday_5pm_rates(csv_file=csv_file)
        generate_sql_import_script(csv_file)
    
    elif args.mode == 'reference':
        # If CSV exists, extract from it; otherwise generate synthetic
        csv_file = 'mock_rates_current.csv' if Path('mock_rates_current.csv').exists() else None
        if csv_file:
            print(f"Found {csv_file}, will extract reference rates from it")
        generate_yesterday_5pm_rates(csv_file=csv_file)
    
    elif args.mode == 'streaming':
        # For streaming, generate reference rates first (synthetic is OK)
        print("=" * 60)
        print("STREAMING MODE - Generating reference rates")
        print("=" * 60)
        generate_yesterday_5pm_rates(csv_file=None)  # Synthetic for streaming
        
        # Then stream data
        generate_streaming_kafka(args.duration)


if __name__ == '__main__':
    main()
