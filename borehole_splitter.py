#!/usr/bin/env python3
"""
Borehole Log Splitter & Extractor CLI Wrapper
---------------------------------------------
Author: Antigravity (AI Coding Assistant)
Description:
    A thin wrapper for executing the borehole log splitter and stratigraphy 
    extraction pipeline, calling the orchestration logic inside jobs/run_pipeline.py.
"""

import sys
from jobs.run_pipeline import main

if __name__ == "__main__":
    main()
