#!/usr/bin/env python
"""
PCIe-7821 DAS Acquisition Software
Quick launch script

Usage:
    python run.py              # Normal mode (requires hardware)
    python run.py --simulate   # Simulation mode (no hardware required)
    python run.py --debug      # Enable debug logging
    python run.py --log FILE   # Save log to file
"""

import sys
import os

# Add src directory to Python path
src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
sys.path.insert(0, src_path)

# Import and run main
from main import main

if __name__ == '__main__':
    main()
