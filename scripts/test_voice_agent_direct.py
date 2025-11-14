#!/usr/bin/env python3
"""
Direct Voice Agent Testing Script

Spawns voice agent directly without orchestrator/celery for rapid testing.

Usage:
    python scripts/test_voice_agent_direct.py --session-id test_123
    python scripts/test_voice_agent_direct.py --session-id my_test --voice-id Ashley
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def main():
    parser = argparse.ArgumentParser(
        description='Spawn voice agent directly for testing (bypasses orchestrator/celery)'
    )
    parser.add_argument('--session-id', required=True, help='Session ID (room name)')
    parser.add_argument('--voice-id', default='Ashley', help='Voice ID (default: Ashley)')
    parser.add_argument('--opening-line', default='Hello! This is a test session.',
                        help='Opening greeting line')
    parser.add_argument('--system-prompt', default='You are a helpful AI voice assistant.',
                        help='System prompt for LLM')

    args = parser.parse_args()

    # Build environment
    env = os.environ.copy()
    env['TEST_MODE'] = 'true'
    env['LOG_LEVEL'] = 'DEBUG'
    env['PYTHONPATH'] = str(project_root)

    # Build command
    cmd = [
        'python3',
        str(project_root / 'backend' / 'agent' / 'voice_assistant.py'),
        '--room', args.session_id,
        '--voice-id', args.voice_id,
        '--opening-line', args.opening_line,
        '--system-prompt', args.system_prompt
    ]

    print("=" * 60)
    print("SPAWNING VOICE AGENT (TEST MODE)")
    print("=" * 60)
    print(f"Session ID: {args.session_id}")
    print(f"Voice ID: {args.voice_id}")
    print(f"TEST_MODE: true")
    print("=" * 60)

    # Spawn process
    process = subprocess.Popen(cmd, env=env)
    print(f"\n✓ Voice agent spawned: PID {process.pid}")
    print("Agent is running. Press Ctrl+C to stop.\n")

    try:
        process.wait()
    except KeyboardInterrupt:
        print("\n\nStopping voice agent...")
        process.terminate()
        process.wait()
        print("✓ Voice agent stopped")


if __name__ == '__main__':
    main()
