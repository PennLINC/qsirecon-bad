#!/usr/bin/env python
import sys
import warnings
from argparse import ArgumentParser, RawTextHelpFormatter
from pathlib import Path

from ..viz.reports import generate_interactive_report_summary

warnings.filterwarnings("ignore", category=ImportWarning)
warnings.filterwarnings("ignore", category=PendingDeprecationWarning)


def aggregate_reports():
    """Convert fib to mif."""
    parser = ArgumentParser(
        description="qsipost: Aggregate single subject reports into a group report.",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        "qsipost_derivatives_dir",
        type=Path,
        action="store",
        help="the root folder containing QSIPost outputs (sub-XXXXX folders "
        "should be found at the top level in this folder).",
    )
    opts = parser.parse_args()
    sys.exit(generate_interactive_report_summary(opts.qsipost_derivatives_dir))
