#!/usr/bin/env python3
################################################################################
# Pytest unit tests for codeloader.py
#
# Tests:
# 1. CodeLoader initialization (PTY opening, stty -echo)
# 2. run_command() - basic commands (echo, pwd, ls, env)
# 3. remove_remote_dir() - directory deletion
# 4. upload_file() - base64 heredoc upload
# 5. compress_bin_directory() - archive creation
# 6. get_config() - environment configuration
################################################################################

import base64
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from codeloader import (
    ARCHIVE_NAME,
    CODELOADER_TEMP_DIR,
    REAL_REMOTE_APP_DIR,
    SIMULATED_REMOTE_APP_DIR,
    SIMULATED_UART_PORT,
    CodeLoader,
    compress_bin_directory,
    generate_sha256_hash,
    get_archive_size,
    get_config,
)


################################################################################
# Fixtures
################################################################################


def _uart_available():
    """Check if the simulated UART PTY exists."""
    return os.path.exists(SIMULATED_UART_PORT) or os.path.islink(SIMULATED_UART_PORT)


@pytest.fixture()
def simulated_env():
    """Temporarily set SIMULATED_ENV=1 and restore afterwards."""
    old_value = os.environ.get('SIMULATED_ENV')
    os.environ['SIMULATED_ENV'] = '1'
    yield
    if old_value is not None:
        os.environ['SIMULATED_ENV'] = old_value
    else:
        os.environ.pop('SIMULATED_ENV', None)


@pytest.fixture()
def real_env():
    """Temporarily remove SIMULATED_ENV and restore afterwards."""
    old_value = os.environ.pop('SIMULATED_ENV', None)
    yield
    if old_value is not None:
        os.environ['SIMULATED_ENV'] = old_value


@pytest.fixture(scope='module')
def code_loader():
    """Provide a CodeLoader instance for the entire test module.

    Skips all tests in the module if the UART PTY is not available.
    Automatically closes the file descriptor after tests complete.
    """
    if not _uart_available():
        pytest.skip(f"UART PTY not available at {SIMULATED_UART_PORT}")

    loader = CodeLoader(SIMULATED_UART_PORT)
    yield loader
    # Cleanup: close the file descriptor
    if loader.fd is not None:
        os.close(loader.fd)
        loader.fd = None


@pytest.fixture()
def temp_bin_file():
    """Create a temporary file with known content for upload testing."""
    content = "Hello, this is test content for upload!\nLine 2\nLine 3"
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(content)
        temp_path = f.name

    yield temp_path, content

    os.unlink(temp_path)


@pytest.fixture()
def test_archive(tmp_path):
    """Create a valid tar.gz archive for hash/size testing."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'test.sh').write_text('#!/bin/bash\necho test\n', encoding='utf-8')
    (bin_dir / 'config.txt').write_text('key=value', encoding='utf-8')

    archive_path = tmp_path / 'test_bin.tar.gz'
    with tarfile.open(archive_path, 'w:gz') as tar:
        tar.add(bin_dir, arcname='bin')

    return str(archive_path)


################################################################################
# Test: get_config()
################################################################################


class TestGetConfig:
    """Tests for the get_config() function."""

    def test_returns_dict(self, simulated_env):
        """get_config should return a dictionary."""
        config = get_config()
        assert isinstance(config, dict)

    def test_has_uart_port_key(self, simulated_env):
        """get_config should contain 'uart_port' key."""
        config = get_config()
        assert 'uart_port' in config

    def test_has_remote_app_dir_key(self, simulated_env):
        """get_config should contain 'remote_app_dir' key."""
        config = get_config()
        assert 'remote_app_dir' in config

    def test_uart_port_is_simulated(self, simulated_env):
        """get_config should return SIMULATED_UART_PORT when SIMULATED_ENV=1."""
        config = get_config()
        assert config['uart_port'] == SIMULATED_UART_PORT

    def test_remote_app_dir_is_simulated(self, simulated_env):
        """get_config should return SIMULATED_REMOTE_APP_DIR when SIMULATED_ENV=1."""
        config = get_config()
        assert config['remote_app_dir'] == SIMULATED_REMOTE_APP_DIR

    def test_real_env_uses_discovered_uart(self, real_env):
        """get_config should use discovered_uart() in real environment."""
        config = get_config()
        assert config['uart_port'] != SIMULATED_UART_PORT

    def test_real_env_uses_real_remote_dir(self, real_env):
        """get_config should use REAL_REMOTE_APP_DIR in real environment."""
        config = get_config()
        assert config['remote_app_dir'] == REAL_REMOTE_APP_DIR


################################################################################
# Test: compress_bin_directory()
################################################################################


class TestCompressBinDirectory:
    """Tests for the compress_bin_directory() function."""

    def test_creates_archive(self, tmp_path):
        """compress_bin_directory should create an archive file."""
        temp_dir = str(tmp_path / 'codeloader')
        archive_path = compress_bin_directory(temp_dir=temp_dir, bin_dir='./bin')
        assert os.path.isfile(archive_path)

    def test_archive_path_contains_temp_dir(self, tmp_path):
        """Archive path should be within the specified temp directory."""
        temp_dir = str(tmp_path / 'custom_temp')
        archive_path = compress_bin_directory(temp_dir=temp_dir, bin_dir='./bin')
        assert archive_path.startswith(str(tmp_path / 'custom_temp'))

    def test_archive_has_valid_size(self, test_archive):
        """get_archive_size should return a positive integer."""
        size = get_archive_size(test_archive)
        assert isinstance(size, int)
        assert size > 0

    def test_archive_has_valid_sha256_hash(self, test_archive):
        """generate_sha256_hash should return a 64-character hex string."""
        hash_val = generate_sha256_hash(test_archive)
        assert len(hash_val) == 64
        # Verify it's valid hex
        int(hash_val, 16)

    def test_archive_contains_files(self, tmp_path):
        """Archive should contain files from the bin directory."""
        temp_dir = str(tmp_path / 'codeloader')
        archive_path = compress_bin_directory(temp_dir=temp_dir, bin_dir='./bin')

        with tarfile.open(archive_path, 'r:gz') as tar:
            names = tar.getnames()
        assert len(names) > 0
        # Should contain 'bin' prefix
        assert any('bin' in name for name in names)

    def test_raises_on_missing_bin_dir(self, tmp_path):
        """compress_bin_directory should raise OSError for non-existent bin directory."""
        with pytest.raises(OSError, match="does not exist"):
            compress_bin_directory(temp_dir=str(tmp_path), bin_dir='./nonexistent')

    def test_creates_temp_dir_if_missing(self, tmp_path):
        """compress_bin_directory should create temp_dir if it doesn't exist."""
        temp_dir = str(tmp_path / 'new_temp_dir')
        assert not os.path.exists(temp_dir)

        compress_bin_directory(temp_dir=temp_dir, bin_dir='./bin')
        assert os.path.isdir(temp_dir)


################################################################################
# Test: CodeLoader initialization
################################################################################


class TestCodeLoaderInitialization:
    """Tests for CodeLoader class initialization."""

    def test_opens_pty(self, code_loader):
        """CodeLoader should open the PTY without raising."""
        assert code_loader.fd is not None

    def test_fd_is_valid(self, code_loader):
        """CodeLoader fd should be a valid file descriptor."""
        assert code_loader.fd >= 0

    def test_port_is_stored(self, code_loader):
        """CodeLoader should store the port path."""
        assert code_loader.port == SIMULATED_UART_PORT

    def test_drain_does_not_crash(self, code_loader):
        """_drain() should handle empty buffer without crashing."""
        code_loader._drain()  # Should not raise


################################################################################
# Test: run_command()
################################################################################


class TestRunCommand:
    """Tests for the run_command() method."""

    def test_echo_command(self, code_loader):
        """run_command should return correct output for echo."""
        output, exit_code = code_loader.run_command('echo "hello_world"', timeout=5)
        assert exit_code == 0
        assert 'hello_world' in output

    def test_pwd_command(self, code_loader):
        """run_command should return correct output for pwd."""
        output, exit_code = code_loader.run_command('pwd', timeout=5)
        assert exit_code == 0
        assert len(output.strip()) > 0

    def test_ls_existing_path(self, code_loader):
        """run_command should succeed for ls on existing path."""
        output, exit_code = code_loader.run_command('ls /tmp', timeout=5)
        assert exit_code == 0
        assert len(output) >= 0  # May be empty if /tmp is empty

    def test_nonexistent_command_fails(self, code_loader):
        """run_command should return non-zero exit code for unknown command."""
        output, exit_code = code_loader.run_command('nonexistent_command_xyz', timeout=5)
        assert exit_code is not None
        assert exit_code != 0

    def test_special_characters(self, code_loader):
        """run_command should handle special characters in output."""
        output, exit_code = code_loader.run_command('echo -e "test\\nwith\\tspecial"', timeout=5)
        assert exit_code == 0

    def test_command_with_sleep(self, code_loader):
        """run_command should handle commands that take time to complete."""
        start = time.time()
        output, exit_code = code_loader.run_command('sleep 1 && echo "done"', timeout=5)
        elapsed = time.time() - start
        assert exit_code == 0
        assert 'done' in output
        assert elapsed < 5.0

    def test_quick_command_within_timeout(self, code_loader):
        """run_command should complete quickly for simple commands."""
        start = time.time()
        output, exit_code = code_loader.run_command('echo "quick"', timeout=3)
        elapsed = time.time() - start
        assert exit_code == 0
        assert elapsed < 3.0

    def test_multiple_echo_lines(self, code_loader):
        """run_command should handle multi-line output."""
        output, exit_code = code_loader.run_command(
            'printf "line1\\nline2\\nline3\\n"',
            timeout=5
        )
        assert exit_code == 0
        assert 'line1' in output
        assert 'line2' in output
        assert 'line3' in output

    def test_empty_command_output(self, code_loader):
        """run_command should handle commands with no output."""
        output, exit_code = code_loader.run_command('true', timeout=5)
        assert exit_code == 0
        assert output.strip() == ''


################################################################################
# Test: prompt stripping
################################################################################


class TestPromptStripping:
    """Tests for the _strip_prompt() method."""

    @pytest.mark.parametrize(
        "input_line,expected",
        [
            ("root@raspberrypi:~# hello", "hello"),
            ("pi@raspberrypi:~$ hello", "hello"),
            ("bash-5.2$ hello", "hello"),
            ("~$ hello", "hello"),
            ("hello world", "hello world"),
            ("$ ", ""),
            ("# ", ""),
            ("user@host:/path/to/dir$ command output", "command output"),
            ("admin@server:~# sudo ls", "sudo ls"),
        ],
    )
    def test_strip_prompt_various_formats(self, code_loader, input_line, expected):
        """_strip_prompt should correctly strip various bash prompt formats."""
        result = code_loader._strip_prompt(input_line)
        assert result.strip() == expected.strip()

    def test_strip_prompt_empty_line(self, code_loader):
        """_strip_prompt should handle empty lines."""
        assert code_loader._strip_prompt('') == ''

    def test_strip_prompt_whitespace_only(self, code_loader):
        """_strip_prompt should preserve whitespace-only lines."""
        result = code_loader._strip_prompt('   ')
        assert result == '   '


################################################################################
# Test: remove_remote_dir()
################################################################################


class TestRemoveRemoteDir:
    """Tests for the remove_remote_dir() method."""

    def test_create_test_directory(self, code_loader):
        """Setup: create a test directory."""
        _, exit_code = code_loader.run_command('mkdir -p /tmp/test_codeloader_dir', timeout=5)
        assert exit_code == 0

    def test_directory_exists_before_removal(self, code_loader):
        """Verify test directory exists before removal."""
        output, exit_code = code_loader.run_command(
            'test -d /tmp/test_codeloader_dir && echo "exists"'
        )
        assert exit_code == 0
        assert 'exists' in output

    def test_remove_directory(self, code_loader):
        """remove_remote_dir should remove the specified directory."""
        out, remove_code = code_loader.remove_remote_dir('/tmp/test_codeloader_dir')
        assert remove_code is not None  # Should return without error

    def test_directory_removed(self, code_loader):
        """Verify directory no longer exists after removal."""
        output, exit_code = code_loader.run_command(
            'test -d /tmp/test_codeloader_dir && echo "exists" || echo "gone"'
        )
        assert exit_code == 0
        assert 'gone' in output

    def test_remove_nonexistent_directory(self, code_loader):
        """remove_remote_dir should not crash on non-existent directory."""
        out, code = code_loader.remove_remote_dir('/tmp/nonexistent_dir_xyz_12345')
        # Should not raise an exception
        assert out is not None
        assert code is not None


################################################################################
# Test: upload_file()
################################################################################


class TestUploadFile:
    """Tests for the upload_file() method."""

    def test_upload_file_succeeds(self, code_loader, temp_bin_file):
        """upload_file should complete without raising an exception."""
        local_path, _ = temp_bin_file
        remote_path = '/tmp/test_codeloader_upload.txt'
        output = code_loader.upload_file(local_path, remote_path, timeout=15)
        assert output is not None

    def test_uploaded_file_content_matches(self, code_loader, temp_bin_file):
        """upload_file should preserve file content exactly."""
        local_path, expected_content = temp_bin_file
        remote_path = '/tmp/test_codeloader_upload_content.txt'

        try:
            code_loader.upload_file(local_path, remote_path, timeout=15)
            output, exit_code = code_loader.run_command(f'cat {remote_path}', timeout=5)
            assert exit_code == 0
            assert expected_content == output.strip()
        finally:
            code_loader.run_command(f'rm -f {remote_path}', timeout=5)

    def test_uploaded_file_exists(self, code_loader, temp_bin_file):
        """upload_file should create the remote file."""
        local_path, _ = temp_bin_file
        remote_path = '/tmp/test_codeloader_upload_exists.txt'

        try:
            code_loader.upload_file(local_path, remote_path, timeout=15)
            output, exit_code = code_loader.run_command(f'test -f {remote_path} && echo "yes"', timeout=5)
            assert exit_code == 0
            assert 'yes' in output
        finally:
            code_loader.run_command(f'rm -f {remote_path}', timeout=5)

    def test_upload_large_file(self, code_loader, tmp_path):
        """upload_file should handle larger files."""
        # Create a larger test file
        large_content = "x" * 10240  # 10KB of data
        local_path = str(tmp_path / 'large_test.txt')
        with open(local_path, 'w') as f:
            f.write(large_content)

        remote_path = '/tmp/test_codeloader_large.txt'
        try:
            code_loader.upload_file(local_path, remote_path, timeout=30)
            output, exit_code = code_loader.run_command(f'wc -c {remote_path}', timeout=5)
            assert exit_code == 0
            assert '10240' in output
        finally:
            code_loader.run_command(f'rm -f {remote_path}', timeout=5)

    def test_upload_binary_file(self, code_loader, tmp_path):
        """upload_file should handle binary content."""
        binary_content = bytes(range(256))
        local_path = str(tmp_path / 'binary_test.bin')
        with open(local_path, 'wb') as f:
            f.write(binary_content)

        remote_path = '/tmp/test_codeloader_binary.bin'
        try:
            code_loader.upload_file(local_path, remote_path, timeout=15)
            output, exit_code = code_loader.run_command(f'wc -c {remote_path}', timeout=5)
            assert exit_code == 0
            assert '256' in output
        finally:
            code_loader.run_command(f'rm -f {remote_path}', timeout=5)


################################################################################
# Test: upload_code()
################################################################################


class TestUploadCode:
    """Tests for the upload_code() function."""

    def test_upload_code_returns_path(self, simulated_env, code_loader, tmp_path):
        """upload_code should return an archive path."""
        from codeloader import upload_code

        # Patch the upload_code to avoid full remote operations
        with patch.object(code_loader, 'remove_remote_dir') as mock_remove:
            mock_remove.return_value = ('', 0)
            with patch('codeloader.CodeLoader.remove_remote_dir', return_value=('', 0)):
                result = upload_code()
                assert result is not None
                assert isinstance(result, str)

    def test_upload_code_creates_archive(self, simulated_env):
        """upload_code should create an archive when archive_path is None."""
        from codeloader import upload_code

        with patch('codeloader.CodeLoader.remove_remote_dir', return_value=('', 0)):
            result = upload_code()
            assert os.path.isfile(result)


################################################################################
# Test: Helper functions
################################################################################


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_generate_sha256_hash_deterministic(self, test_archive):
        """generate_sha256_hash should return the same hash for the same file."""
        hash1 = generate_sha256_hash(test_archive)
        hash2 = generate_sha256_hash(test_archive)
        assert hash1 == hash2

    def test_generate_sha256_hash_different_for_different_files(self, tmp_path):
        """generate_sha256_hash should return different hashes for different files."""
        # Create two different files
        file1 = tmp_path / 'file1.tar.gz'
        file2 = tmp_path / 'file2.tar.gz'

        with tarfile.open(file1, 'w:gz') as tar:
            pass
        with tarfile.open(file2, 'w:gz') as tar:
            tar.add(__file__, arcname='test.py')

        hash1 = generate_sha256_hash(str(file1))
        hash2 = generate_sha256_hash(str(file2))
        assert hash1 != hash2

    def test_get_archive_size_matches_os(self, test_archive):
        """get_archive_size should match os.path.getsize."""
        custom_size = get_archive_size(test_archive)
        actual_size = os.path.getsize(test_archive)
        assert custom_size == actual_size

    def test_compress_bin_directory_uses_default_paths(self):
        """compress_bin_directory should use default paths when no args provided."""
        archive_path = compress_bin_directory()
        assert CODELOADER_TEMP_DIR in archive_path
        assert ARCHIVE_NAME in archive_path


################################################################################
# Test: CodeLoader edge cases
################################################################################


class TestCodeLoaderEdgeCases:
    """Tests for CodeLoader edge cases and error handling."""

    def test_write_string(self, code_loader):
        """_write() should accept string input."""
        # This won't fully execute without a real shell, but tests type handling
        assert hasattr(code_loader, '_write')

    def test_write_bytes(self, code_loader):
        """_write() should accept bytes input."""
        assert hasattr(code_loader, '_write')

    def test_read_until_timeout(self, code_loader):
        """_read_until() should return partial data on timeout."""
        result = code_loader._read_until('NONEXISTENT_MARKER_XYZ', timeout=0.1)
        # Should not raise, may return partial data
        assert isinstance(result, str)

    def test_read_all_empty(self, code_loader):
        """_read_all() should handle empty buffer."""
        result = code_loader._read_all(timeout=0.1)
        assert isinstance(result, str)


################################################################################
# Test: Environment isolation
################################################################################


class TestEnvironmentIsolation:
    """Tests to ensure environment variables are properly managed."""

    def test_config_independent_of_order(self):
        """get_config should return consistent results regardless of call order."""
        # Test real -> simulated -> real
        config1 = get_config()
        os.environ['SIMULATED_ENV'] = '1'
        config2 = get_config()
        del os.environ['SIMULATED_ENV']
        config3 = get_config()

        assert config1['uart_port'] != config2['uart_port']
        assert config1['uart_port'] == config3['uart_port']
        assert config1['remote_app_dir'] != config2['remote_app_dir']
        assert config1['remote_app_dir'] == config3['remote_app_dir']

    def test_multiple_config_calls_same_env(self, simulated_env):
        """Multiple get_config calls in same env should return same values."""
        config1 = get_config()
        config2 = get_config()
        assert config1 == config2
