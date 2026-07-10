#!/usr/bin/env python3
"""
Creates a new per-project folder scaffold at the repo root:
  Project - <Name>/
    Borehole Reports/
    individual borehole logs/
    outputs/
    results/

Each blank subfolder gets a .gitkeep so git tracks the empty structure.
"""
import argparse
import os
import sys

SUBFOLDERS = ["Borehole Reports", "individual borehole logs", "outputs", "results"]


def main():
    parser = argparse.ArgumentParser(description="Scaffold a new project folder with the standard 4 subfolders.")
    parser.add_argument("--name", required=True, help="Project name (without the 'Project - ' prefix)")
    args = parser.parse_args()

    project_name = args.name.strip()
    if project_name.lower().startswith("project - "):
        project_name = project_name[len("project - "):].strip()

    project_dir = f"Project - {project_name}"

    if os.path.exists(project_dir):
        print(f"[Error] '{project_dir}' already exists.", file=sys.stderr)
        sys.exit(1)

    for sub in SUBFOLDERS:
        sub_path = os.path.join(project_dir, sub)
        os.makedirs(sub_path, exist_ok=True)
        with open(os.path.join(sub_path, ".gitkeep"), "w", encoding="utf-8"):
            pass

    print(f"Created project scaffold: {project_dir}/")
    for sub in SUBFOLDERS:
        print(f"  - {project_dir}/{sub}/")


if __name__ == "__main__":
    main()
