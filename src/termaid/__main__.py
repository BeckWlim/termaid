"""Allow running termaid as a module: python -m termaid"""
import sys

from termaid.cli import main

sys.exit(main())
