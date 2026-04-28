#!/usr/bin/env python3
################################################################################
# Tests for the utility functions in codeloader.
#
# These tests verify the standalone utility functions including:
# - compress_bin_directory()
# - get_archive_size()
# - generate_sha256_hash()
# - get_config()
# - discovered_uart()
################################################################################

import os
import sys
import hashlib
import tarfile
import pytest
from unittest.mock import patch, MagicMock

# Add parent directory to path so we can import codeloader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import codeloader


###############
# TestCompressBinDirectory
#
# Tests for compress_bin_directory() which creates a tar.gz archive
# of the bin directory.
###############

class TestCompressBinDirectory:
    """Tests for codeloader.compress_bin_directory()."""

    def test_compress_creates_archive(self, temp_bin_directory, tmp_path):
        """Test that compress_bin_directory creates a tar.gz archive."""
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory
        )
        assert os.path.exists(archive_path)
        assert archive_path.endswith('.tar.gz')

    def test_compress_archive_contains_bin(self, temp_bin_directory, tmp_path):
        """Test that the archive contains the bin directory."""
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory
        )
        with tarfile.open(archive_path, 'r:gz') as tar:
            names = tar.getnames()
            assert any('bin' in name for name in names)

    def test_compress_archive_contains_entry_sh(self, temp_bin_directory, tmp_path):
        """Test that the archive contains entry.sh."""
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory
        )
        with tarfile.open(archive_path, 'r:gz') as tar:
            names = tar.getnames()
            assert any('entry.sh' in name for name in names)

    def test_compress_nonexistent_directory_raises(self, tmp_path):
        """Test that compressing a nonexistent directory raises OSError."""
        temp_dir = str(tmp_path / 'temp')
        with pytest.raises(OSError, match="does not exist"):
            codeloader.compress_bin_directory(
                temp_dir=temp_dir,
                bin_dir='/nonexistent/path/to/bin'
            )

    def test_compress_creates_temp_dir(self, temp_bin_directory, tmp_path):
        """Test that compress creates the temp directory if it doesn't exist."""
        temp_dir = str(tmp_path / 'new_temp_dir')
        assert not os.path.exists(temp_dir)

        codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory
        )
        assert os.path.exists(temp_dir)

    def test_compress_with_custom_archive_name(self, temp_bin_directory, tmp_path):
        """Test compressing with a custom archive name."""
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory,
            archive_name='custom_archive.tar.gz'
        )
        assert os.path.exists(archive_path)
        assert 'custom_archive.tar.gz' in archive_path


###############
# TestGetArchiveSize
#
# Tests for get_archive_size() which returns the file size in bytes.
###############

class TestGetArchiveSize:
    """Tests for codeloader.get_archive_size()."""

    def test_get_archive_size_returns_bytes(self, temp_bin_directory, tmp_path):
        """Test that get_archive_size returns the file size in bytes."""
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory
        )
        size = codeloader.get_archive_size(archive_path)
        assert isinstance(size, int)
        assert size > 0

    def test_get_archive_size_matches_os(self, temp_bin_directory, tmp_path):
        """Test that get_archive_size matches os.path.getsize."""
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory
        )
        size = codeloader.get_archive_size(archive_path)
        expected_size = os.path.getsize(archive_path)
        assert size == expected_size


###############
# TestGenerateSha256Hash
#
# Tests for generate_sha256_hash() which computes SHA256 hash of a file.
###############

class TestGenerateSha256Hash:
    """Tests for codeloader.generate_sha256_hash()."""

    def test_generate_hash_returns_string(self, temp_bin_directory, tmp_path):
        """Test that generate_sha256_hash returns a string."""
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory
        )
        hash_value = codeloader.generate_sha256_hash(archive_path)
        assert isinstance(hash_value, str)

    def test_generate_hash_length(self, temp_bin_directory, tmp_path):
        """Test that the hash is 64 characters (SHA256 hex digest)."""
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory
        )
        hash_value = codeloader.generate_sha256_hash(archive_path)
        assert len(hash_value) == 64

    def test_generate_hash_matches_python_hashlib(self, temp_bin_directory, tmp_path):
        """Test that the hash matches Python's hashlib."""
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory
        )
        hash_value = codeloader.generate_sha256_hash(archive_path)

        # Compute expected hash using hashlib
        sha256 = hashlib.sha256()
        with open(archive_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        expected_hash = sha256.hexdigest()

        assert hash_value == expected_hash

    def test_generate_hash_consistent(self, temp_bin_directory, tmp_path):
        """Test that hashing the same file twice gives the same result."""
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=temp_bin_directory
        )
        hash1 = codeloader.generate_sha256_hash(archive_path)
        hash2 = codeloader.generate_sha256_hash(archive_path)
        assert hash1 == hash2


###############
# TestGetConfig
#
# Tests for get_config() which returns configuration based on environment.
###############

class TestGetConfig:
    """Tests for codeloader.get_config()."""

    def test_get_config_simulated(self, simulated_env):
        """Test get_config returns simulated values when SIMULATED_ENV=1."""
        config = codeloader.get_config()
        assert config['uart_port'] == codeloader.SIMULATED_UART_PORT
        assert config['remote_app_dir'] == codeloader.SIMULATED_REMOTE_APP_DIR

    def test_get_config_simulated_returns_dict(self, simulated_env):
        """Test that get_config returns a dictionary."""
        config = codeloader.get_config()
        assert isinstance(config, dict)
        assert 'uart_port' in config
        assert 'remote_app_dir' in config

    def test_get_config_real_exits_without_uart(self):
        """Test get_config calls discovered_uart when not in simulated mode.
        
        This test patches discovered_uart to verify it's called in non-simulated mode.
        """
        # Remove SIMULATED_ENV to trigger real mode
        old_value = os.environ.pop('SIMULATED_ENV', None)
        try:
            with patch('codeloader.discovered_uart') as mock_discover:
                mock_discover.return_value = '/dev/ttyUSB0'
                config = codeloader.get_config()
                mock_discover.assert_called_once()
                assert config['uart_port'] == '/dev/ttyUSB0'
                assert config['remote_app_dir'] == codeloader.REAL_REMOTE_APP_DIR
        finally:
            if old_value is not None:
                os.environ['SIMULATED_ENV'] = old_value


###############
# TestDiscoveredUart
#
# Tests for discovered_uart() which scans for USB UART devices.
###############

class TestDiscoveredUart:
    """Tests for codeloader.discovered_uart()."""

    def test_discovered_uart_finds_device(self):
        """Test that discovered_uart returns a port when available."""
        # Mock serial.tools.list_ports.comports to return a fake port
        fake_port = MagicMock()
        fake_port.device = '/dev/ttyUSB0'
        fake_port.vid = 0x1234
        fake_port.pid = 0x5678

        with patch('serial.tools.list_ports.comports') as mock_comports:
            mock_comports.return_value = [fake_port]
            result = codeloader.discovered_uart()
            assert result == '/dev/ttyUSB0'

    def test_discovered_uart_returns_first_device(self):
        """Test that discovered_uart returns the first available device."""
        fake_port1 = MagicMock()
        fake_port1.device = '/dev/ttyUSB0'
        fake_port1.vid = 0x1234
        fake_port1.pid = 0x5678

        fake_port2 = MagicMock()
        fake_port2.device = '/dev/ttyUSB1'
        fake_port2.vid = 0x1234
        fake_port2.pid = 0x5678

        with patch('serial.tools.list_ports.comports') as mock_comports:
            mock_comports.return_value = [fake_port1, fake_port2]
            result = codeloader.discovered_uart()
            assert result == '/dev/ttyUSB0'

    def test_discovered_uart_skips_non_usb(self):
        """Test that discovered_uart skips ports without vid/pid."""
        # First port has no vid/pid (not USB)
        fake_port1 = MagicMock()
        fake_port1.device = '/dev/ttyS0'
        fake_port1.vid = None
        fake_port1.pid = None

        # Second port is USB
        fake_port2 = MagicMock()
        fake_port2.device = '/dev/ttyUSB0'
        fake_port2.vid = 0x1234
        fake_port2.pid = 0x5678

        with patch('serial.tools.list_ports.comports') as mock_comports:
            mock_comports.return_value = [fake_port1, fake_port2]
            result = codeloader.discovered_uart()
            assert result == '/dev/ttyUSB0'

    def test_discovered_uart_exits_when_no_device(self):
        """Test that discovered_uart exits when no USB device found."""
        with patch('serial.tools.list_ports.comports') as mock_comports:
            mock_comports.return_value = []
            with pytest.raises(SystemExit) as exc_info:
                codeloader.discovered_uart()
            assert exc_info.value.code == 1
