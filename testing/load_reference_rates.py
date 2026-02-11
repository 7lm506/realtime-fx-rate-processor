#!/usr/bin/env python3
"""
Load Reference Rates to PostgreSQL (Docker)
============================================

Loads yesterday_rates.json to yesterday_5pm_rates table in Docker PostgreSQL.

Usage:
    python load_reference_rates.py
"""

import json
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("Error: psycopg2 not installed")
    print("Run: pip install psycopg2-binary")
    sys.exit(1)

# Configuration
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'dbname': 'fxdb',
    'user': 'postgres',
    'password': 'postgres'
}

REFERENCE_RATES_FILE = 'testing/yesterday_rates.json'

def load_reference_rates():
    """Load reference rates from JSON to database"""
    
    # Check if file exists
    if not Path(REFERENCE_RATES_FILE).exists():
        print(f"Error: {REFERENCE_RATES_FILE} not found")
        print("Run: python testing/generate_mock_data.py --mode full")
        sys.exit(1)
    
    # Load JSON
    print(f"Loading reference rates from {REFERENCE_RATES_FILE}...")
    with open(REFERENCE_RATES_FILE, 'r') as f:
        rates = json.load(f)
    
    print(f"Found {len(rates)} reference rates")
    
    # Connect to database
    try:
        conn_string = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
        print(f"Connecting to database: {conn_string.replace(DB_CONFIG['password'], '***')}")
        
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Insert each rate
        for ccy, rate in rates.items():
            cur.execute("""
                INSERT INTO yesterday_5pm_rates (ccy_couple, rate, reference_date, snapshot_time)
                VALUES (%s, %s, CURRENT_DATE, CURRENT_TIMESTAMP - INTERVAL '1 day')
                ON CONFLICT (ccy_couple, reference_date) 
                DO UPDATE SET 
                    rate = EXCLUDED.rate,
                    snapshot_time = EXCLUDED.snapshot_time
            """, (ccy, rate))
            print(f"  ✓ {ccy}: {rate}")
        
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"\n✓ Successfully loaded {len(rates)} reference rates!")
        return True
        
    except psycopg2.OperationalError as e:
        print(f"\nError: Cannot connect to PostgreSQL")
        print(f"Details: {e}")
        print("\nMake sure Docker services are running:")
        print("  docker-compose up -d")
        print("  sleep 30  # Wait for PostgreSQL")
        return False
        
    except psycopg2.ProgrammingError as e:
        print(f"\nError: Database or table doesn't exist")
        print(f"Details: {e}")
        print("\nMake sure you've created the schema:")
        print("  docker-compose exec -T postgres psql -U postgres -d fxdb < sql/create_tables_part_b.sql")
        return False
        
    except Exception as e:
        print(f"\nError: {e}")
        return False

if __name__ == '__main__':
    success = load_reference_rates()
    sys.exit(0 if success else 1)
