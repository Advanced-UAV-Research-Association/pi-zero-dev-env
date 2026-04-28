#!/usr/bin/env python3
################################################################################
# Test configuration and fixtures for codeloader tests.
#
# This module provides pytest fixtures and setup for testing the codeloader
# module with the simulated UART interface at /tmp/ttyUART0.
################################################################################

import os
import pytest
import subprocess
import time
import shutil

# Path to the simulated UART interface
SIMULATED_UART_PORT = '/tmp/ttyUART0'


###############
# Helpers
###############

def is_uart_available():
    """Check if the simulated UART interface is available."""
    return os.path.exists(SIMULATED_UART_PORT)


def start_uart_simulation():
    """Start the UART simulation if not already running."""
    script_path = os.path.join(
        os.path.dirname(__file__),
        '..', '.devcontainer', 'scripts', 'start_uart_sim.sh'
    )
    script_path = os.path.abspath(script_path)

    if not os.path.exists(script_path):
        return False

    result = subprocess.run(
        ['bash', script_path],
        capture_output=True,
        text=True
    )

    time.sleep(1)
    return result.returncode == 0


def stop_uart_simulation():
    """Stop the UART simulation."""
    pidfile = '/tmp/uart-sim.pid'
    if os.path.exists(pidfile):
        try:
            with open(pidfile, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, 15)
            time.sleep(0.5)
        except (ValueError, ProcessLookupError, PermissionError):
            pass


def ensure_uart_ready(timeout=10):
    """Ensure UART simulation is running and ready."""
    if is_uart_available():
        return True

    if start_uart_simulation():
        waited = 0
        while not is_uart_available() and waited < timeout:
            time.sleep(0.5)
            waited += 0.5
        return is_uart_available()

    return False


###############
# Fixtures
###############

@pytest.fixture(scope='session', autouse=True)
def uart_simulation_session():
    """Session-scoped fixture to manage UART simulation lifecycle.

    Ensures the UART simulation is running before any tests execute.
    Skips all tests if the simulation cannot be started.
    """
    simulated_env = os.environ.get('SIMULATED_ENV')

    if simulated_env != '1':
        pytest.skip("SIMULATED_ENV=1 not set, skipping UART-dependent tests")

    if not ensure_uart_ready():
        pytest.skip("UART simulation not available or failed to start")

    yield

    # Leave running for debugging


@pytest.fixture
def uart_port():
    """Provide the UART port path."""
    return SIMULATED_UART_PORT


@pytest.fixture(autouse=True)
def simulated_env():
    """Set SIMULATED_ENV=1 for tests that need it.

    This fixture is auto-used to ensure all tests run in simulated mode.
    """
    old_value = os.environ.get('SIMULATED_ENV')
    os.environ['SIMULATED_ENV'] = '1'
    yield
    if old_value is None:
        os.environ.pop('SIMULATED_ENV', None)
    else:
        os.environ['SIMULATED_ENV'] = old_value


@pytest.fixture
def temp_bin_directory(tmp_path):
    """Create a temporary bin directory with test files.

    Creates a bin directory with an entry.sh script for testing
    archive creation and upload workflows.
    """
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()

    entry_sh = bin_dir / 'entry.sh'
    entry_sh.write_text('#!/bin/bash\necho "Hello from test entry.sh"\nexit 0\n')
    entry_sh.chmod(0o755)

    return str(bin_dir)


@pytest.fixture
def temp_test_file(tmp_path):
    """Create a temporary test file for upload tests."""
    test_file = tmp_path / 'test.txt'
    test_file.write_text('Hello, World!\nThis is a test file.\n')
    return str(test_file)


@pytest.fixture
def remote_temp_dir():
    """Provide a temporary remote directory path for testing."""
    remote_dir = '/tmp/codeloader_test_remote'
    # Clean up before test
    if os.path.exists(remote_dir):
        shutil.rmtree(remote_dir)
    yield remote_dir
    # Clean up after test
    if os.path.exists(remote_dir):
        shutil.rmtree(remote_dir)
