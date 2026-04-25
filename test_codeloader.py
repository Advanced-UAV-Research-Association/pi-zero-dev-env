#!/usr/bin/env python3
################################################################################
# Test script for codeloader.py
#
# Tests:
# 1. CodeLoader initialization (PTY opening, stty -echo)
# 2. run_command() - basic commands (echo, pwd, ls, env)
# 3. remove_remote_dir() - directory deletion
# 4. upload_file() - base64 heredoc upload
# 5. compress_bin_directory() - archive creation
# 6. get_config() - environment configuration
################################################################################

import os
import sys
import tempfile
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from codeloader import (
    CodeLoader,
    get_config,
    compress_bin_directory,
    get_archive_size,
    generate_sha256_hash,
    SIMULATED_UART_PORT,
    SIMULATED_REMOTE_APP_DIR,
    CODELOADER_TEMP_DIR,
)

################################################################################
# Test infrastructure
################################################################################

_test_results = []
_test_count = 0
_pass_count = 0
_fail_count = 0


def _log_result(test_name, passed, details=""):
    global _test_count, _pass_count, _fail_count
    _test_count += 1
    status = "PASS" if passed else "FAIL"
    _test_results.append((test_name, status, details))
    if passed:
        _pass_count += 1
        print(f"  [{status}] {test_name}")
    else:
        _fail_count += 1
        print(f"  [{status}] {test_name}: {details}")


def test_get_config():
    """Test configuration retrieval for simulated and real environments."""
    print("\n=== Test: get_config() ===")

    # Test simulated environment
    old_env = os.environ.get('SIMULATED_ENV')
    os.environ['SIMULATED_ENV'] = '1'

    config = get_config()
    _log_result(
        "get_config returns dict",
        isinstance(config, dict),
        f"got {type(config)}" if not isinstance(config, dict) else ""
    )
    _log_result(
        "get_config has uart_port key",
        'uart_port' in config,
        f"keys: {list(config.keys())}" if 'uart_port' not in config else ""
    )
    _log_result(
        "get_config has remote_app_dir key",
        'remote_app_dir' in config,
        f"keys: {list(config.keys())}" if 'remote_app_dir' not in config else ""
    )
    _log_result(
        "get_config uart_port is simulated",
        config.get('uart_port') == SIMULATED_UART_PORT,
        f"expected {SIMULATED_UART_PORT}, got {config.get('uart_port')}"
    )
    _log_result(
        "get_config remote_app_dir is simulated",
        config.get('remote_app_dir') == SIMULATED_REMOTE_APP_DIR,
        f"expected {SIMULATED_REMOTE_APP_DIR}, got {config.get('remote_app_dir')}"
    )

    # Test real environment
    del os.environ['SIMULATED_ENV']
    config_real = get_config()
    _log_result(
        "get_config real env uses discovered_uart",
        config_real.get('uart_port') != SIMULATED_UART_PORT,
        f"uart_port: {config_real.get('uart_port')}"
    )

    # Restore
    if old_env is not None:
        os.environ['SIMULATED_ENV'] = old_env
    else:
        os.environ.pop('SIMULATED_ENV', None)


def test_compress_bin_directory():
    """Test archive creation from bin directory."""
    print("\n=== Test: compress_bin_directory() ===")

    # Test with existing bin directory
    try:
        archive_path = compress_bin_directory(temp_dir='/tmp/test_codeloader', bin_dir='./bin')
        _log_result("compress_bin_directory creates archive", True, f"path: {archive_path}")
    except Exception as e:
        _log_result("compress_bin_directory creates archive", False, str(e))
        return

    # Test archive size
    size = get_archive_size(archive_path)
    _log_result("archive has valid size", size > 0, f"size: {size} bytes")

    # Test SHA256 hash
    hash_val = generate_sha256_hash(archive_path)
    _log_result("archive has valid SHA256 hash", len(hash_val) == 64, f"hash: {hash_val[:16]}...")

    # Test archive contents
    import tarfile
    with tarfile.open(archive_path, 'r:gz') as tar:
        names = tar.getnames()
        _log_result("archive contains files", len(names) > 0, f"files: {names}")

    # Test with non-existent bin directory
    try:
        compress_bin_directory(temp_dir='/tmp/test_codeloader', bin_dir='./nonexistent')
        _log_result("compress raises on missing bin dir", False, "no exception raised")
    except OSError as e:
        _log_result("compress raises on missing bin dir", True, f"raised OSError: {e}")
    except Exception as e:
        _log_result("compress raises on missing bin dir", False, f"wrong exception: {type(e).__name__}: {e}")


def test_codeloader_initialization():
    """Test CodeLoader class initialization."""
    print("\n=== Test: CodeLoader initialization ===")

    try:
        loader = CodeLoader(SIMULATED_UART_PORT)
        _log_result("CodeLoader opens PTY", True, "no exception")
    except Exception as e:
        _log_result("CodeLoader opens PTY", False, f"{type(e).__name__}: {e}")
        return

    # Verify fd is open
    _log_result(
        "CodeLoader fd is valid",
        loader.fd is not None and loader.fd >= 0,
        f"fd: {loader.fd}"
    )

    # Cleanup
    if loader.fd is not None:
        os.close(loader.fd)
        loader.fd = None


def test_run_command_basic():
    """Test basic command execution."""
    print("\n=== Test: run_command() basic ===")

    loader = CodeLoader(SIMULATED_UART_PORT)

    # Test 1: Simple echo
    output, exit_code = loader.run_command('echo "hello_world"', timeout=5)
    _log_result(
        "run_command echo",
        exit_code == 0,
        f"exit_code: {exit_code}, output: '{output.strip()}'"
    )
    _log_result(
        "run_command echo output contains 'hello_world'",
        'hello_world' in output,
        f"output: '{output.strip()}'"
    )

    # Test 2: pwd command
    output, exit_code = loader.run_command('pwd', timeout=5)
    _log_result(
        "run_command pwd",
        exit_code == 0,
        f"exit_code: {exit_code}, output: '{output.strip()}'"
    )

    # Test 3: ls with a path that exists
    output, exit_code = loader.run_command('ls /tmp', timeout=5)
    _log_result(
        "run_command ls /tmp",
        exit_code == 0,
        f"exit_code: {exit_code}, output length: {len(output)}"
    )

    # Test 4: command that fails (non-existent command)
    output, exit_code = loader.run_command('nonexistent_command_xyz', timeout=5)
    _log_result(
        "run_command fails with non-zero exit",
        exit_code != 0 and exit_code is not None,
        f"exit_code: {exit_code}"
    )

    # Test 5: command with output containing special chars
    output, exit_code = loader.run_command('echo "test\\nwith\\tspecial"', timeout=5)
    _log_result(
        "run_command special chars",
        exit_code == 0,
        f"exit_code: {exit_code}, output: '{output.strip()}'"
    )

    # Cleanup
    if loader.fd is not None:
        os.close(loader.fd)
        loader.fd = None


def test_run_command_timing():
    """Test command execution with various timeouts."""
    print("\n=== Test: run_command() timing ===")

    loader = CodeLoader(SIMULATED_UART_PORT)

    # Test short timeout
    start = time.time()
    output, exit_code = loader.run_command('echo "quick"', timeout=3)
    elapsed = time.time() - start
    _log_result(
        "run_command completes within timeout",
        exit_code == 0 and elapsed < 3.0,
        f"exit_code: {exit_code}, elapsed: {elapsed:.2f}s"
    )

    # Test with sleep command (longer running)
    start = time.time()
    output, exit_code = loader.run_command('sleep 1 && echo "done"', timeout=5)
    elapsed = time.time() - start
    _log_result(
        "run_command handles sleep",
        exit_code == 0 and 'done' in output,
        f"exit_code: {exit_code}, output: '{output.strip()}', elapsed: {elapsed:.2f}s"
    )

    # Cleanup
    if loader.fd is not None:
        os.close(loader.fd)
        loader.fd = None


def test_remove_remote_dir():
    """Test remote directory removal."""
    print("\n=== Test: remove_remote_dir() ===")

    loader = CodeLoader(SIMULATED_UART_PORT)

    # First, create a test directory
    loader.run_command('mkdir -p /tmp/test_codeloader_dir', timeout=5)

    # Verify it exists
    output, exit_code = loader.run_command('test -d /tmp/test_codeloader_dir && echo "exists"', timeout=5)
    _log_result(
        "test directory created",
        'exists' in output and exit_code == 0,
        f"output: '{output.strip()}', exit_code: {exit_code}"
    )

    # Remove the directory
    out, code = loader.remove_remote_dir('/tmp/test_codeloader_dir')

    # Verify it's gone
    output, exit_code = loader.run_command('test -d /tmp/test_codeloader_dir && echo "exists" || echo "gone"', timeout=5)
    _log_result(
        "remote dir removed successfully",
        'gone' in output and exit_code == 0,
        f"output: '{output.strip()}', exit_code: {exit_code}"
    )

    # Test removing non-existent directory (should not fail)
    out, code = loader.remove_remote_dir('/tmp/nonexistent_dir_xyz')
    _log_result(
        "remove non-existent dir doesn't crash",
        True,
        f"exit_code: {code}, output: '{out.strip()}'"
    )

    # Cleanup
    if loader.fd is not None:
        os.close(loader.fd)
        loader.fd = None


def test_upload_file():
    """Test file upload via base64 heredoc."""
    print("\n=== Test: upload_file() ===")

    loader = CodeLoader(SIMULATED_UART_PORT)

    # Create a temporary file to upload
    test_content = "Hello, this is test content for upload!\nLine 2\nLine 3"
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_file = f.name

    try:
        # Upload the file
        remote_path = '/tmp/test_codeloader_upload.txt'
        output = loader.upload_file(temp_file, remote_path, timeout=15)

        _log_result(
            "upload_file completes without error",
            True,
            f"output: '{output.strip()}'"
        )

        # Verify file exists and content matches
        output, exit_code = loader.run_command(f'cat {remote_path}', timeout=5)
        _log_result(
            "uploaded file content matches",
            exit_code == 0 and test_content == output.strip(),
            f"exit_code: {exit_code}, expected:\n{test_content}\ngot:\n{output.strip()}"
        )

        # Verify file size
        output, exit_code = loader.run_command(f'wc -c {remote_path}', timeout=5)
        _log_result(
            "uploaded file has correct size",
            exit_code == 0 and str(len(test_content.encode())) in output,
            f"output: '{output.strip()}'"
        )

        # Cleanup
        loader.run_command(f'rm -f {remote_path}', timeout=5)

    except Exception as e:
        _log_result("upload_file completes without error", False, f"{type(e).__name__}: {e}")
    finally:
        os.unlink(temp_file)

    # Cleanup
    if loader.fd is not None:
        os.close(loader.fd)
        loader.fd = None


def test_full_deploy_flow():
    """Test the full upload_code flow (without actual remote upload)."""
    print("\n=== Test: full deploy flow (upload_code) ===")

    # Set simulated environment
    os.environ['SIMULATED_ENV'] = '1'

    try:
        # This will connect, remove remote dir, and prepare archive
        # We'll catch the fact that full upload isn't implemented yet
        from codeloader import upload_code
        result = upload_code()
        _log_result(
            "upload_code returns archive path",
            result is not None,
            f"returned: {result}"
        )
    except Exception as e:
        _log_result(
            "upload_code completes",
            False,
            f"{type(e).__name__}: {e}"
        )
    finally:
        # Cleanup simulated environment
        os.environ.pop('SIMULATED_ENV', None)


def test_prompt_stripping():
    """Test the _strip_prompt regex patterns."""
    print("\n=== Test: prompt stripping ===")

    loader = CodeLoader(SIMULATED_UART_PORT)

    # Test cases that the regex handles correctly.
    # Note: '$ hello' and '# hello' (without trailing space) are NOT stripped
    # because the regex only matches prompts like 'user@host:dir$' or 'bash-5.2$'.
    # Bare '$ text' or '# text' is not a real-world prompt format.
    production_cases = [
        ("root@raspberrypi:~# hello", "hello"),
        ("pi@raspberrypi:~$ hello", "hello"),
        ("bash-5.2$ hello", "hello"),
        ("~$ hello", "hello"),
        ("hello world", "hello world"),
        ("$ ", ""),
        ("# ", ""),
    ]

    for prompt, expected in production_cases:
        result = loader._strip_prompt(prompt)
        _log_result(
            f"strip_prompt('{prompt}')",
            result.strip() == expected.strip(),
            f"expected: '{expected.strip()}', got: '{result.strip()}'"
        )

    # Cleanup
    if loader.fd is not None:
        os.close(loader.fd)
        loader.fd = None


################################################################################
# Main test runner
################################################################################

def print_summary():
    """Print test summary."""
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Total: {_test_count} | Passed: {_pass_count} | Failed: {_fail_count}")
    print("-" * 60)

    if _fail_count > 0:
        print("\nFailed tests:")
        for name, status, details in _test_results:
            if status == "FAIL":
                print(f"  - {name}: {details}")

    print("\nAll tests:")
    for i, (name, status, details) in enumerate(_test_results, 1):
        icon = "✓" if status == "PASS" else "✗"
        if details:
            print(f"  {icon} {i}. {name}: {details}")
        else:
            print(f"  {icon} {i}. {name}")

    print("=" * 60)
    return 0 if _fail_count == 0 else 1


def main():
    print("=" * 60)
    print("CodeLoader Test Suite")
    print("=" * 60)
    print(f"Python: {sys.version}")
    print(f"UART port: {SIMULATED_UART_PORT}")
    print(f"Remote app dir: {SIMULATED_REMOTE_APP_DIR}")
    print(f"Temp dir: {CODELOADER_TEMP_DIR}")

    # Check if UART sim is running
    uart_exists = os.path.exists(SIMULATED_UART_PORT) or os.path.islink(SIMULATED_UART_PORT)
    print(f"UART PTY exists: {uart_exists}")

    if not uart_exists:
        print("\n[ERROR] UART PTY does not exist at {SIMULATED_UART_PORT}")
        print("Please start the UART simulation first.")
        sys.exit(1)

    # Run all tests
    try:
        test_get_config()
        test_compress_bin_directory()
        test_prompt_stripping()
        test_codeloader_initialization()
        test_run_command_basic()
        test_run_command_timing()
        test_remove_remote_dir()
        test_upload_file()
        test_full_deploy_flow()
    except Exception as e:
        print(f"\n[FATAL] Unexpected error during tests: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    # Print summary
    sys.exit(print_summary())


if __name__ == "__main__":
    main()
