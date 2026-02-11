#!/usr/bin/env python3
"""
LED DISPLAY VISUALIZATION - REAL-TIME CONSOLE DASHBOARD
========================================================

Creates a live-updating terminal dashboard that simulates an LED display.
Shows FX rates with colors, arrows, and real-time updates.

Usage:
    python led_display_visual.py

Requirements:
    pip install rich kafka-python
"""

import json
import signal
import sys
import time
from collections import OrderedDict
from datetime import datetime
from typing import Dict, Optional

from kafka import KafkaConsumer
from kafka.errors import KafkaError
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Display configuration"""
    KAFKA_BOOTSTRAP_SERVERS = ['localhost:9092']
    KAFKA_TOPIC = 'fx-rates-led-display'  # Output topic from processor
    UPDATE_INTERVAL = 0.1  # Screen refresh rate (seconds)
    MAX_DISPLAY_PAIRS = 10  # How many pairs to show
    
    # Colors
    COLOR_POSITIVE = "green"
    COLOR_NEGATIVE = "red"
    COLOR_NEUTRAL = "yellow"
    COLOR_HEADER = "cyan"


# ============================================================================
# DATA MODEL
# ============================================================================

class DisplayRate:
    """Represents a rate for display"""
    
    def __init__(self, ccy_couple: str, rate: float, change: str):
        self.ccy_couple = ccy_couple.strip('"')  # Remove quotes
        self.rate = rate
        self.change = change.strip('"')  # Remove quotes
        self.last_update = time.time()
        
        # Parse change to determine direction
        if change == '"N/A"' or change == 'N/A':
            self.direction = "neutral"
            self.change_value = 0.0
        elif '+' in change:
            self.direction = "up"
            self.change_value = float(change.replace('"', '').replace('%', '').replace('+', ''))
        elif '-' in change:
            self.direction = "down"
            self.change_value = float(change.replace('"', '').replace('%', '').replace('-', ''))
        else:
            self.direction = "neutral"
            self.change_value = 0.0
    
    def get_arrow(self) -> str:
        """Get arrow symbol for direction"""
        if self.direction == "up":
            return "↑"
        elif self.direction == "down":
            return "↓"
        else:
            return "-"
    
    def get_color(self) -> str:
        """Get color based on direction"""
        if self.direction == "up":
            return Config.COLOR_POSITIVE
        elif self.direction == "down":
            return Config.COLOR_NEGATIVE
        else:
            return Config.COLOR_NEUTRAL
    
    def age_seconds(self) -> float:
        """How old is this rate?"""
        return time.time() - self.last_update


# ============================================================================
# LED DISPLAY MANAGER
# ============================================================================

class LEDDisplayManager:
    """Manages the LED display state and rendering"""
    
    def __init__(self):
        self.console = Console()
        self.rates: OrderedDict[str, DisplayRate] = OrderedDict()
        self.stats = {
            'total_updates': 0,
            'start_time': time.time(),
            'last_update_time': None
        }
        self.running = False
    
    def update_rate(self, ccy_couple: str, rate: float, change: str):
        """Update a rate in the display"""
        self.rates[ccy_couple] = DisplayRate(ccy_couple, rate, change)
        self.stats['total_updates'] += 1
        self.stats['last_update_time'] = time.time()
        
        # Keep only most recent pairs
        if len(self.rates) > Config.MAX_DISPLAY_PAIRS:
            self.rates.popitem(last=False)  # Remove oldest
    
    def get_active_pairs(self) -> int:
        """Count active pairs (updated in last 30 seconds)"""
        return sum(1 for rate in self.rates.values() if rate.age_seconds() < 30)
    
    def get_update_rate(self) -> float:
        """Calculate updates per second"""
        elapsed = time.time() - self.stats['start_time']
        if elapsed > 0:
            return self.stats['total_updates'] / elapsed
        return 0.0
    
    def create_table(self) -> Table:
        """Create Rich table for display"""
        table = Table(
            title="FX RATES - LED DISPLAY SIMULATION",
            title_style=f"bold {Config.COLOR_HEADER}",
            show_header=True,
            header_style=f"bold {Config.COLOR_HEADER}",
            border_style=Config.COLOR_HEADER,
            expand=True
        )
        
        # Define columns
        table.add_column("Currency Pair", justify="left", style="bold", width=15)
        table.add_column("Rate", justify="right", width=12)
        table.add_column("Change", justify="right", width=12)
        table.add_column("", justify="center", width=3)  # Arrow
        table.add_column("Last Update", justify="right", width=10)
        
        # Add rows for each rate
        for ccy, rate_obj in self.rates.items():
            # Format last update time
            age = rate_obj.age_seconds()
            if age < 1:
                age_str = "<1s ago"
            elif age < 60:
                age_str = f"{int(age)}s ago"
            else:
                age_str = f"{int(age/60)}m ago"
            
            # Color based on direction
            color = rate_obj.get_color()
            
            table.add_row(
                Text(rate_obj.ccy_couple, style="bold white"),
                Text(f"{rate_obj.rate:.5f}", style=color),
                Text(rate_obj.change, style=color),
                Text(rate_obj.get_arrow(), style=color),
                Text(age_str, style="dim")
            )
        
        # Add empty row if no data
        if not self.rates:
            table.add_row(
                Text("Waiting for data...", style="dim italic"),
                "-", "-", "-", "-"
            )
        
        return table
    
    def create_stats_panel(self) -> Panel:
        """Create statistics panel"""
        active_pairs = self.get_active_pairs()
        update_rate = self.get_update_rate()
        
        stats_text = Text()
        stats_text.append(f"Total Updates: ", style="bold")
        stats_text.append(f"{self.stats['total_updates']:,}", style="cyan")
        stats_text.append("  |  ", style="dim")
        stats_text.append(f"Active Pairs: ", style="bold")
        stats_text.append(f"{active_pairs}", style="green" if active_pairs > 0 else "red")
        stats_text.append("  |  ", style="dim")
        stats_text.append(f"Update Rate: ", style="bold")
        stats_text.append(f"{update_rate:.1f} msg/sec", style="yellow")
        
        return Panel(
            stats_text,
            border_style="blue",
            padding=(0, 1)
        )
    
    def create_footer(self) -> Text:
        """Create footer with timestamp and instructions"""
        footer = Text()
        
        if self.stats['last_update_time']:
            last_update = datetime.fromtimestamp(self.stats['last_update_time'])
            footer.append(f"Last update: {last_update.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", style="dim")
        else:
            footer.append("Waiting for first update...", style="dim italic")
        
        footer.append("  |  ", style="dim")
        footer.append("Press Ctrl+C to stop", style="dim italic")
        
        return footer
    
    def create_layout(self) -> Layout:
        """Create complete layout"""
        layout = Layout()
        
        # Build layout
        layout.split(
            Layout(name="header", size=1),
            Layout(name="main", ratio=1),
            Layout(name="stats", size=3),
            Layout(name="footer", size=1)
        )
        
        # Populate layout
        layout["header"].update(Text("═" * 80, style=Config.COLOR_HEADER))
        layout["main"].update(self.create_table())
        layout["stats"].update(self.create_stats_panel())
        layout["footer"].update(self.create_footer())
        
        return layout


# ============================================================================
# KAFKA CONSUMER
# ============================================================================

class LEDDisplayConsumer:
    """Consumes LED display output from Kafka and updates display"""
    
    def __init__(self):
        self.display = LEDDisplayManager()
        self.consumer = None
        self.running = False
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.console.print("\n[yellow]Shutting down...[/yellow]")
        self.running = False
    
    def initialize_kafka(self):
        """Initialize Kafka consumer"""
        try:
            self.consumer = KafkaConsumer(
                Config.KAFKA_TOPIC,
                bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
                value_deserializer=lambda m: m.decode('utf-8'),
                auto_offset_reset='latest',
                enable_auto_commit=True,
                group_id='led-display-visual'
            )
            return True
        except KafkaError as e:
            self.console.print(f"[red]Failed to connect to Kafka: {e}[/red]")
            return False
    
    def parse_message(self, message: str) -> Optional[tuple]:
        """
        Parse LED display message.
        
        Format: "EUR/USD",1.08077,"+0.123%"
        Returns: (ccy_couple, rate, change)
        """
        try:
            parts = message.split(',')
            if len(parts) == 3:
                ccy = parts[0].strip('"')
                rate = float(parts[1])
                change = parts[2]
                return (ccy, rate, change)
        except Exception as e:
            self.console.print(f"[red]Error parsing message: {e}[/red]")
        return None
    
    def run(self):
        """Main display loop"""
        self.console = Console()
        
        # Initialize Kafka
        if not self.initialize_kafka():
            return
        
        self.running = True
        
        # Show startup message
        self.console.print("\n[bold green]LED Display Starting...[/bold green]")
        self.console.print(f"Consuming from Kafka topic: [cyan]{Config.KAFKA_TOPIC}[/cyan]")
        self.console.print(f"Brokers: [cyan]{Config.KAFKA_BOOTSTRAP_SERVERS}[/cyan]")
        self.console.print("\n[yellow]Waiting for data...[/yellow]\n")
        time.sleep(2)
        
        # Start live display
        with Live(
            self.display.create_layout(),
            refresh_per_second=10,
            screen=True
        ) as live:
            
            try:
                for message in self.consumer:
                    if not self.running:
                        break
                    
                    # Parse message
                    parsed = self.parse_message(message.value)
                    if parsed:
                        ccy, rate, change = parsed
                        self.display.update_rate(ccy, rate, change)
                    
                    # Update display
                    live.update(self.display.create_layout())
                    
            except KeyboardInterrupt:
                pass
            except Exception as e:
                self.console.print(f"\n[red]Error: {e}[/red]")
            finally:
                if self.consumer:
                    self.consumer.close()
        
        # Show exit message
        self.console.print("\n[green]Display stopped.[/green]")
        self.console.print(f"Total updates received: [cyan]{self.display.stats['total_updates']:,}[/cyan]")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='LED Display Visualization',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  # Start visualization
  python led_display_visual.py
  
  # With custom Kafka brokers
  python led_display_visual.py --kafka-brokers broker1:9092,broker2:9092

Make sure:
  1. Kafka is running
  2. Producer is sending data (generate_mock_data.py)
  3. Processor is running (fx_rates_streaming.py)
        """
    )
    
    parser.add_argument(
        '--kafka-brokers',
        type=str,
        default='localhost:9092',
        help='Kafka bootstrap servers (comma-separated)'
    )
    parser.add_argument(
        '--topic',
        type=str,
        default='fx-rates-led-display',
        help='Kafka topic to consume from'
    )
    parser.add_argument(
        '--max-pairs',
        type=int,
        default=10,
        help='Maximum number of pairs to display'
    )
    
    args = parser.parse_args()
    
    # Update config
    Config.KAFKA_BOOTSTRAP_SERVERS = args.kafka_brokers.split(',')
    Config.KAFKA_TOPIC = args.topic
    Config.MAX_DISPLAY_PAIRS = args.max_pairs
    
    # Run display
    consumer = LEDDisplayConsumer()
    consumer.run()


if __name__ == '__main__':
    main()


"""
============================================================================
INSTALLATION:
============================================================================

pip install rich kafka-python

============================================================================
USAGE:
============================================================================

# Terminal 1: Start Kafka
docker-compose up -d

# Terminal 2: Start Producer
python generate_mock_data.py --mode streaming

# Terminal 3: Start Processor
python fx_rates_streaming.py

# Terminal 4: Start LED Display Visualization
python led_display_visual.py

============================================================================
EXPECTED OUTPUT:
============================================================================

╔══════════════════════════════════════════════════════════════╗
║              FX RATES - LED DISPLAY SIMULATION               ║
║                    Real-Time Streaming                       ║
╠══════════════════════════════════════════════════════════════╣
║ Currency Pair    Rate         Change        Last Update      ║
╠══════════════════════════════════════════════════════════════╣
║ EUR/USD          1.08077      +0.001%  ↑    <1s ago         ║
║ GBP/USD          1.26230      -0.050%  ↓    2s ago          ║
║ AUD/USD          0.65490      +0.123%  ↑    1s ago          ║
║ NZD/USD          0.61642       N/A     -    3s ago          ║
║ EUR/GBP          0.85619      +0.050%  ↑    <1s ago         ║
╠══════════════════════════════════════════════════════════════╣
║ Total Updates: 1,234  |  Active: 5  |  Rate: 45.2 msg/sec  ║
╚══════════════════════════════════════════════════════════════╝

Last update: 2024-12-10 15:23:45.123  |  Press Ctrl+C to stop

============================================================================
"""
