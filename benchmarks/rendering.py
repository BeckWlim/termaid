"""Reproducible editor-style rendering benchmark; timings are not test gates."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1] / 'src')
    parser.add_argument('--fixtures', type=Path, default=Path(__file__).resolve().parents[1] / 'tests/fixtures')
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--cold', action='store_true', help='Include Python process startup, as Neovim does')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    sys.path.insert(0, str(args.source_root.resolve()))
    from termaid.cli import main as render_cli
    render_environment = {**os.environ, 'PYTHONPATH': str(args.source_root.resolve())}

    measurements = []
    for fixture in ('production_architecture', 'production_supervisor_state', 'production_lease_race'):
        for width in (68, 100, 160):
            gap = max(1, min(4, width // 40))
            command = [str(args.fixtures / (fixture + '.mmd')), '--width', str(width),
                       '--strict-width', '--fit-mode', 'reflow', '--gap', str(gap),
                       '--padding-x', str(min(gap, 2)), '--padding-y', '0',
                       '--max-height', '4096', '--format', 'styled-json']
            elapsed_samples: list[float] = []
            output_text = ''
            for iteration in range(args.repeats + 1):
                output_buffer = StringIO()
                error_buffer = StringIO()
                started_at = time.perf_counter()
                if args.cold:
                    process_result = subprocess.run(
                        [sys.executable, '-m', 'termaid', *command], env=render_environment,
                        capture_output=True, text=True, check=False,
                    )
                    result_code = process_result.returncode
                    output_text = process_result.stdout
                    error_text = process_result.stderr
                else:
                    with redirect_stdout(output_buffer), redirect_stderr(error_buffer):
                        result_code = render_cli(command)
                    output_text = output_buffer.getvalue()
                    error_text = error_buffer.getvalue()
                elapsed_seconds = time.perf_counter() - started_at
                if result_code or error_text:
                    raise RuntimeError(f'{fixture}/{width}: {error_text}')
                if iteration:
                    elapsed_samples.append(elapsed_seconds)
            document = json.loads(output_text)
            measurements.append({
                'fixture': fixture, 'width': width,
                'median_ms': 1000 * statistics.median(elapsed_samples),
                'min_ms': 1000 * min(elapsed_samples),
                'max_ms': 1000 * max(elapsed_samples),
                'output_rows': len(document['lines']),
                'output_bytes': len(output_text.encode()),
                'sha256': hashlib.sha256(output_text.encode()).hexdigest(),
            })
    args.output.write_text(json.dumps({
        'source_root': str(args.source_root.resolve()), 'python': sys.version,
        'repeats': args.repeats, 'cold': args.cold, 'measurements': measurements,
    }, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
