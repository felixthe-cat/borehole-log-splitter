#!/usr/bin/env python3
"""
Borehole Log Splitter & Extractor CLI Wrapper (Skill Directory)
---------------------------------------------------------------
Author: Antigravity (AI Coding Assistant)
Description:
    Redirects calls to the master job runner in the project root.
"""

import os
import sys

# Add project root to sys.path to resolve imports correctly
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, project_root)

from borehole_splitter import main

if __name__ == "__main__":
    main()
