#!/usr/bin/env python3
################################################################################
# Tests for codeloader.py standalone utility functions
#
# Tests for:
#   - get_config()
#   - discovered_uart()
#   - compress_bin_directory()
#   - get_archive_size()
#   - generate_sha256_hash()
#   - upload_code() (mocked)
#   - run_code() (mocked)
################################################################################

import hashlib
import os
import sys
import tarfile
from unittest.mock import MagicMock, patch

import pytest

from codeloader import (
    ARCHIVE_NAME,
    CODELOADER_TEMP_DIR,
    LOCAL_BIN_DIR,
    REAL_REMOTE_APP_DIR,
    SIMULATED_REMOTE_APP_DIR,
    SIMULATED_UART_PORT,
    compress_bin_directory,
    discovered_uart,
    generate_sha256_hash,
    get_archive_size,
    get_config,
    run_code,
    upload_code,
)


# Helper to compute expected hash response for upload tests
def _make_hash_response(archive_path):
    """Compute the expected hash response for a given archive path."""
    with open(archive_path, 'rb') as f:
        local_hash = hashlib.sha256(f.read()).hexdigest()
    remote_path = '/tmp/app/bin.tar.gz'
    return f"{local_hash}  {remote_path}"


################################################################################
# TestGetConfig
################################################################################

class TestGetConfig:
    """Tests for get_config() function."""

    def test_get_config_simulated_environment(self, monkeypatch):
        """Test config returns simulated values when SIMULATED_ENV=1."""
        monkeypatch.setenv('SIMULATED_ENV', '1')
        config = get_config()
        assert config['uart_port'] == SIMULATED_UART_PORT
        assert config['remote_app_dir'] == SIMULATED_REMOTE_APP_DIR

    def test_get_config_returns_dict(self, monkeypatch):
        """Test return type is dictionary."""
        monkeypatch.setenv('SIMULATED_ENV', '1')
        config = get_config()
        assert isinstance(config, dict)

    def test_get_config_has_required_keys(self, monkeypatch):
        """Test dict contains 'uart_port' and 'remote_app_dir'."""
        monkeypatch.setenv('SIMULATED_ENV', '1')
        config = get_config()
        assert 'uart_port' in config
        assert 'remote_app_dir' in config

    def test_get_config_simulated_port_value(self, monkeypatch):
        """Test port is '/tmp/ttyUART0' when simulated."""
        monkeypatch.setenv('SIMULATED_ENV', '1')
        config = get_config()
        assert config['uart_port'] == '/tmp/ttyUART0'

    def test_get_config_simulated_app_dir_value(self, monkeypatch):
        """Test app dir is '/tmp/app' when simulated."""
        monkeypatch.setenv('SIMULATED_ENV', '1')
        config = get_config()
        assert config['remote_app_dir'] == '/tmp/app'

    def test_get_config_real_app_dir_value(self, monkeypatch):
        """Test app dir is '/app' when real."""
        # Ensure SIMULATED_ENV is not '1'
        monkeypatch.delenv('SIMULATED_ENV', raising=False)
        # We need to mock discovered_uart to avoid actual serial access
        with patch('codeloader.discovered_uart', return_value='/dev/ttyUSB0'):
            config = get_config()
        assert config['remote_app_dir'] == REAL_REMOTE_APP_DIR

    def test_get_config_real_environment(self, monkeypatch):
        """Test returns real values when SIMULATED_ENV not set."""
        monkeypatch.delenv('SIMULATED_ENV', raising=False)
        with patch('codeloader.discovered_uart', return_value='/dev/ttyUSB0'):
            config = get_config()
        assert config['remote_app_dir'] == REAL_REMOTE_APP_DIR
        assert config['uart_port'] == '/dev/ttyUSB0'

    def test_get_config_simulated_env_empty_string(self, monkeypatch):
        """Test empty string is not treated as simulated."""
        monkeypatch.setenv('SIMULATED_ENV', '')
        with patch('codeloader.discovered_uart', return_value='/dev/ttyUSB0'):
            config = get_config()
        assert config['remote_app_dir'] == REAL_REMOTE_APP_DIR


################################################################################
# TestDiscoveredUart
################################################################################

class TestDiscoveredUart:
    """Tests for discovered_uart() function."""

    def test_discovered_uart_returns_string(self):
        """Test returns a string path."""
        mock_port = MagicMock()
        mock_port.vid = 1234
        mock_port.pid = 5678
        mock_port.device = '/dev/ttyUSB0'

        with patch('serial.tools.list_ports.comports') as mock_comports:
            mock_comports.return_value = [mock_port]
            result = discovered_uart()
            assert isinstance(result, str)

    def test_discovered_uart_finds_usb_device(self):
        """Test finds first USB device when available."""
        mock_port = MagicMock()
        mock_port.vid = 1234
        mock_port.pid = 5678
        mock_port.device = '/dev/ttyUSB0'

        with patch('serial.tools.list_ports.comports') as mock_comports:
            mock_comports.return_value = [mock_port]
            result = discovered_uart()
            assert result == '/dev/ttyUSB0'

    def test_discovered_uart_exits_when_no_device(self):
        """Test exits when no USB devices (mocked)."""
        with patch('serial.tools.list_ports.comports') as mock_comports:
            mock_comports.return_value = []
            with pytest.raises(SystemExit) as exc_info:
                discovered_uart()
            assert exc_info.value.code == 1

    def test_discovered_uart_skips_none_vid(self):
        """Test skips ports with None VID."""
        mock_port1 = MagicMock()
        mock_port1.vid = None
        mock_port1.pid = 5678
        mock_port1.device = '/dev/ttyUSB0'

        mock_port2 = MagicMock()
        mock_port2.vid = 1234
        mock_port2.pid = 5678
        mock_port2.device = '/dev/ttyUSB1'

        with patch('serial.tools.list_ports.comports') as mock_comports:
            mock_comports.return_value = [mock_port1, mock_port2]
            result = discovered_uart()
            assert result == '/dev/ttyUSB1'

    def test_discovered_uart_skips_none_pid(self):
        """Test skips ports with None PID."""
        mock_port1 = MagicMock()
        mock_port1.vid = 1234
        mock_port1.pid = None
        mock_port1.device = '/dev/ttyUSB0'

        mock_port2 = MagicMock()
        mock_port2.vid = 1234
        mock_port2.pid = 5678
        mock_port2.device = '/dev/ttyUSB1'

        with patch('serial.tools.list_ports.comports') as mock_comports:
            mock_comports.return_value = [mock_port1, mock_port2]
            result = discovered_uart()
            assert result == '/dev/ttyUSB1'

    def test_discovered_uart_uses_first_valid_device(self):
        """Test uses the first valid device found."""
        mock_port1 = MagicMock()
        mock_port1.vid = 1234
        mock_port1.pid = 5678
        mock_port1.device = '/dev/ttyUSB0'

        mock_port2 = MagicMock()
        mock_port2.vid = 4567
        mock_port2.pid = 8901
        mock_port2.device = '/dev/ttyAMA0'

        with patch('serial.tools.list_ports.comports') as mock_comports:
            mock_comports.return_value = [mock_port1, mock_port2]
            result = discovered_uart()
            assert result == '/dev/ttyUSB0'


################################################################################
# TestCompressBinDirectory
################################################################################

class TestCompressBinDirectory:
    """Tests for compress_bin_directory() function."""

    def test_compress_creates_archive(self, tmp_path):
        """Test archive file is created."""
        # Create test bin directory with a file
        bin_dir = tmp_path / "test_bin"
        bin_dir.mkdir()
        (bin_dir / "test.sh").write_text("#!/bin/bash\necho hello")

        temp_dir = tmp_path / "temp"
        result = compress_bin_directory(
            temp_dir=str(temp_dir),
            bin_dir=str(bin_dir),
            archive_name="test.tar.gz"
        )

        assert os.path.isfile(result)

    def test_compress_returns_path(self, tmp_path):
        """Test returns the archive path."""
        bin_dir = tmp_path / "test_bin"
        bin_dir.mkdir()
        (bin_dir / "test.sh").write_text("#!/bin/bash\necho hello")

        temp_dir = tmp_path / "temp"
        result = compress_bin_directory(
            temp_dir=str(temp_dir),
            bin_dir=str(bin_dir),
            archive_name="test.tar.gz"
        )

        assert result == str(temp_dir / "test.tar.gz")

    def test_compress_creates_valid_tar_gz(self, tmp_path):
        """Test archive is valid gzip tar."""
        bin_dir = tmp_path / "test_bin"
        bin_dir.mkdir()
        (bin_dir / "test.sh").write_text("#!/bin/bash\necho hello")

        temp_dir = tmp_path / "temp"
        archive_path = compress_bin_directory(
            temp_dir=str(temp_dir),
            bin_dir=str(bin_dir),
            archive_name="test.tar.gz"
        )

        # Verify it's a valid tar.gz file
        assert tarfile.is_tarfile(archive_path)
        with tarfile.open(archive_path, 'r:gz') as tar:
            # Should be readable
            assert tar.getnames() is not None

    def test_compress_contains_bin_contents(self, tmp_path):
        """Test archive contains files from bin directory."""
        bin_dir = tmp_path / "test_bin"
        bin_dir.mkdir()
        (bin_dir / "test.sh").write_text("#!/bin/bash\necho hello")
        (bin_dir / "data.txt").write_text("test data")

        temp_dir = tmp_path / "temp"
        archive_path = compress_bin_directory(
            temp_dir=str(temp_dir),
            bin_dir=str(bin_dir),
            archive_name="test.tar.gz"
        )

        with tarfile.open(archive_path, 'r:gz') as tar:
            names = tar.getnames()
            # Should contain the bin directory name and its contents
            assert any('test_bin' in name for name in names)
            assert any('test.sh' in name for name in names)
            assert any('data.txt' in name for name in names)

    def test_compress_raises_on_missing_bin(self, tmp_path):
        """Test OSError when bin directory doesn't exist."""
        non_existent_dir = str(tmp_path / "non_existent_bin")

        with pytest.raises(OSError) as exc_info:
            compress_bin_directory(
                temp_dir=str(tmp_path / "temp"),
                bin_dir=non_existent_dir,
                archive_name="test.tar.gz"
            )

        assert "does not exist" in str(exc_info.value)

    def test_compress_creates_temp_dir(self, tmp_path):
        """Test temp_dir is created if it doesn't exist."""
        bin_dir = tmp_path / "test_bin"
        bin_dir.mkdir()
        (bin_dir / "test.sh").write_text("#!/bin/bash\necho hello")

        # Use a nested non-existent temp directory
        temp_dir = tmp_path / "nested" / "non_existent" / "temp"
        
        result = compress_bin_directory(
            temp_dir=str(temp_dir),
            bin_dir=str(bin_dir),
            archive_name="test.tar.gz"
        )

        assert temp_dir.exists()
        assert os.path.isfile(result)

    def test_compress_custom_parameters(self, tmp_path):
        """Test custom temp_dir, bin_dir, archive_name work."""
        bin_dir = tmp_path / "my_bin"
        bin_dir.mkdir()
        (bin_dir / "script.sh").write_text("#!/bin/bash\necho custom")

        temp_dir = tmp_path / "my_temp"
        archive_name = "custom_archive.tar.gz"

        result = compress_bin_directory(
            temp_dir=str(temp_dir),
            bin_dir=str(bin_dir),
            archive_name=archive_name
        )

        expected_path = str(temp_dir / archive_name)
        assert result == expected_path
        assert os.path.isfile(result)

    def test_compress_archive_is_nonempty(self, tmp_path):
        """Test archive has non-zero size."""
        bin_dir = tmp_path / "test_bin"
        bin_dir.mkdir()
        (bin_dir / "test.sh").write_text("#!/bin/bash\necho hello")

        temp_dir = tmp_path / "temp"
        archive_path = compress_bin_directory(
            temp_dir=str(temp_dir),
            bin_dir=str(bin_dir),
            archive_name="test.tar.gz"
        )

        assert os.path.getsize(archive_path) > 0

    def test_compress_preserves_file_contents(self, tmp_path):
        """Test archive preserves original file contents."""
        bin_dir = tmp_path / "test_bin"
        bin_dir.mkdir()
        original_content = "#!/bin/bash\necho 'Hello World!'\nexit 0"
        (bin_dir / "test.sh").write_text(original_content)

        temp_dir = tmp_path / "temp"
        archive_path = compress_bin_directory(
            temp_dir=str(temp_dir),
            bin_dir=str(bin_dir),
            archive_name="test.tar.gz"
        )

        with tarfile.open(archive_path, 'r:gz') as tar:
            for member in tar.getmembers():
                if member.name.endswith('test.sh'):
                    f = tar.extractfile(member)
                    if f is not None:
                        assert f.read().decode('utf-8') == original_content


################################################################################
# TestGetArchiveSize
################################################################################

class TestGetArchiveSize:
    """Tests for get_archive_size() function."""

    def test_get_archive_size_returns_int(self, tmp_path):
        """Test returns an integer."""
        archive_path = str(tmp_path / "test.tar.gz")
        with open(archive_path, 'w') as f:
            f.write("test content")

        result = get_archive_size(archive_path)
        assert isinstance(result, int)

    def test_get_archive_size_correct_value(self, tmp_path):
        """Test returns correct file size."""
        archive_path = str(tmp_path / "test.tar.gz")
        content = "test content for size verification"
        with open(archive_path, 'w') as f:
            f.write(content)

        result = get_archive_size(archive_path)
        expected_size = len(content.encode('utf-8'))
        assert result == expected_size

    def test_get_archive_size_nonexistent_file(self, tmp_path):
        """Test raises FileNotFoundError for missing file."""
        nonexistent_path = str(tmp_path / "nonexistent.tar.gz")

        with pytest.raises(FileNotFoundError):
            get_archive_size(nonexistent_path)

    def test_get_archive_size_empty_file(self, tmp_path):
        """Test returns 0 for empty file."""
        archive_path = str(tmp_path / "empty.tar.gz")
        with open(archive_path, 'w') as f:
            pass  # Create empty file

        result = get_archive_size(archive_path)
        assert result == 0


################################################################################
# TestGenerateSha256Hash
################################################################################

class TestGenerateSha256Hash:
    """Tests for generate_sha256_hash() function."""

    def test_generate_sha256_hash_returns_string(self, tmp_path):
        """Test returns a string."""
        archive_path = str(tmp_path / "test.tar.gz")
        with open(archive_path, 'w') as f:
            f.write("test content")

        result = generate_sha256_hash(archive_path)
        assert isinstance(result, str)

    def test_generate_sha256_hash_is_correct_length(self, tmp_path):
        """Test returns 64-character hex string."""
        archive_path = str(tmp_path / "test.tar.gz")
        with open(archive_path, 'w') as f:
            f.write("test content")

        result = generate_sha256_hash(archive_path)
        assert len(result) == 64
        # Verify it's valid hex
        int(result, 16)

    def test_generate_sha256_hash_is_deterministic(self, tmp_path):
        """Test same file produces same hash."""
        archive_path = str(tmp_path / "test.tar.gz")
        content = "deterministic test content"
        with open(archive_path, 'w') as f:
            f.write(content)

        hash1 = generate_sha256_hash(archive_path)
        hash2 = generate_sha256_hash(archive_path)
        assert hash1 == hash2

    def test_generate_sha256_hash_different_files(self, tmp_path):
        """Test different files produce different hashes."""
        # Create first file
        file1_path = str(tmp_path / "test1.tar.gz")
        with open(file1_path, 'w') as f:
            f.write("content one")

        # Create second file
        file2_path = str(tmp_path / "test2.tar.gz")
        with open(file2_path, 'w') as f:
            f.write("content two")

        hash1 = generate_sha256_hash(file1_path)
        hash2 = generate_sha256_hash(file2_path)
        assert hash1 != hash2

    def test_generate_sha256_hash_known_value(self, tmp_path):
        """Test verify hash against known value."""
        archive_path = str(tmp_path / "test.tar.gz")
        content = "hello world"
        with open(archive_path, 'w') as f:
            f.write(content)

        expected_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        result = generate_sha256_hash(archive_path)
        assert result == expected_hash

    def test_generate_sha256_hash_nonexistent_file(self, tmp_path):
        """Test raises FileNotFoundError for missing file."""
        nonexistent_path = str(tmp_path / "nonexistent.tar.gz")

        with pytest.raises(FileNotFoundError):
            generate_sha256_hash(nonexistent_path)

    def test_generate_sha256_hash_binary_content(self, tmp_path):
        """Test with binary file content."""
        archive_path = str(tmp_path / "binary.tar.gz")
        content = bytes(range(256))
        with open(archive_path, 'wb') as f:
            f.write(content)

        expected_hash = hashlib.sha256(content).hexdigest()
        result = generate_sha256_hash(archive_path)
        assert result == expected_hash


################################################################################
# TestUploadCode
################################################################################

class TestUploadCode:
    """Integration tests for upload_code() function (mocked)."""

    def test_upload_code_creates_archive(self, monkeypatch, tmp_path):
        """Test archive is created if not provided."""
        # Create a test bin directory
        bin_dir = tmp_path / "test_bin"
        bin_dir.mkdir()
        (bin_dir / "test.sh").write_text("#!/bin/bash\necho hello")

        mock_loader = MagicMock()
        mock_instance = MagicMock()
        mock_loader.return_value = mock_instance

        # Create the archive that will be generated
        temp_archive = tmp_path / "generated.tar.gz"
        temp_archive.write_bytes(b"test archive content")

        def side_effect(cmd, **kwargs):
            if 'sha256sum' in cmd:
                hash_response = _make_hash_response(str(temp_archive))
                return (hash_response, 0)
            return ("", 0)

        mock_instance.run_command.side_effect = side_effect

        mock_compress = MagicMock(return_value=str(temp_archive))

        monkeypatch.setattr('codeloader.CodeLoader', mock_loader)
        monkeypatch.setattr('codeloader.compress_bin_directory', mock_compress)
        monkeypatch.setattr('codeloader.LOCAL_BIN_DIR', str(bin_dir))
        monkeypatch.setenv('SIMULATED_ENV', '1')

        result = upload_code()

        # Should return a path (the created archive)
        assert result is not None
        assert isinstance(result, str)

    def test_upload_code_returns_path(self, monkeypatch, tmp_path):
        """Test returns archive path on success."""
        # Create a test bin directory
        bin_dir = tmp_path / "test_bin"
        bin_dir.mkdir()
        (bin_dir / "test.sh").write_text("#!/bin/bash\necho hello")

        mock_loader = MagicMock()
        mock_instance = MagicMock()
        mock_loader.return_value = mock_instance

        # Create the archive that will be generated
        temp_archive = tmp_path / "generated.tar.gz"
        temp_archive.write_bytes(b"test archive content")

        def side_effect(cmd, **kwargs):
            if 'sha256sum' in cmd:
                hash_response = _make_hash_response(str(temp_archive))
                return (hash_response, 0)
            return ("", 0)

        mock_instance.run_command.side_effect = side_effect

        mock_compress = MagicMock(return_value=str(temp_archive))

        monkeypatch.setattr('codeloader.CodeLoader', mock_loader)
        monkeypatch.setattr('codeloader.compress_bin_directory', mock_compress)
        monkeypatch.setattr('codeloader.LOCAL_BIN_DIR', str(bin_dir))
        monkeypatch.setenv('SIMULATED_ENV', '1')

        result = upload_code()

        assert isinstance(result, str)

    def test_upload_code_uses_provided_archive(self, monkeypatch, tmp_path):
        """Test uses provided archive path."""
        # Create a test archive file
        archive_path = str(tmp_path / "existing.tar.gz")
        with open(archive_path, 'wb') as f:
            f.write(b"existing archive content")

        mock_loader = MagicMock()
        mock_instance = MagicMock()

        def side_effect(cmd, **kwargs):
            if 'sha256sum' in cmd:
                hash_response = _make_hash_response(archive_path)
                return (hash_response, 0)
            return ("", 0)

        mock_instance.run_command.side_effect = side_effect
        mock_loader.return_value = mock_instance

        monkeypatch.setattr('codeloader.CodeLoader', mock_loader)
        monkeypatch.setenv('SIMULATED_ENV', '1')

        result = upload_code(archive_path=archive_path)

        assert result == archive_path

    def test_upload_code_calls_compress_when_no_path(self, monkeypatch, tmp_path):
        """Test compress_bin_directory is called when no archive path provided."""
        bin_dir = tmp_path / "test_bin"
        bin_dir.mkdir()
        (bin_dir / "test.sh").write_text("#!/bin/bash\necho hello")

        # Create the archive file that mock_compress will return
        archive_path = str(tmp_path / "new.tar.gz")
        with open(archive_path, 'wb') as f:
            f.write(b"mock archive content")

        mock_loader = MagicMock()
        mock_instance = MagicMock()

        def side_effect(cmd, **kwargs):
            if 'sha256sum' in cmd:
                hash_response = _make_hash_response(archive_path)
                return (hash_response, 0)
            return ("", 0)

        mock_instance.run_command.side_effect = side_effect
        mock_loader.return_value = mock_instance

        mock_compress = MagicMock(return_value=archive_path)

        monkeypatch.setattr('codeloader.CodeLoader', mock_loader)
        monkeypatch.setattr('codeloader.compress_bin_directory', mock_compress)
        monkeypatch.setattr('codeloader.LOCAL_BIN_DIR', str(bin_dir))
        monkeypatch.setenv('SIMULATED_ENV', '1')

        upload_code()

        mock_compress.assert_called_once()


################################################################################
# TestRunCode
################################################################################

class TestRunCode:
    """Integration tests for run_code() function (mocked)."""

    def test_run_code_handles_missing_entry(self, monkeypatch):
        """Test handles when entry.sh doesn't exist."""
        mock_loader = MagicMock()
        # Simulate command output indicating file doesn't exist
        mock_loader.run_command.return_value = ("", 1)
        
        mock_instance = MagicMock()
        mock_instance.run_command.return_value = ("", 1)
        mock_instance.fd = None
        mock_loader.return_value = mock_instance
        
        monkeypatch.setenv('SIMULATED_ENV', '1')
        monkeypatch.setattr('codeloader.CodeLoader', mock_loader)

        # Should not raise an exception
        run_code()

    def test_run_code_calls_code_loader(self, monkeypatch):
        """Test CodeLoader is instantiated."""
        mock_loader = MagicMock()
        mock_instance = MagicMock()
        mock_instance.run_command.return_value = ("exists", 0)
        mock_instance.fd = None
        mock_loader.return_value = mock_instance
        
        monkeypatch.setenv('SIMULATED_ENV', '1')
        monkeypatch.setattr('codeloader.CodeLoader', mock_loader)

        run_code()
        
        mock_loader.assert_called_once()

    def test_run_code_runs_entry_when_exists(self, monkeypatch):
        """Test entry.sh is run when it exists."""
        mock_loader = MagicMock()
        mock_instance = MagicMock()
        
        # First call checks for entry.sh, second call runs it
        mock_instance.run_command.side_effect = [
            ("exists", 0),  # entry.sh exists
            ("output", 0),  # entry.sh runs
        ]
        mock_instance.fd = None
        mock_loader.return_value = mock_instance
        
        monkeypatch.setenv('SIMULATED_ENV', '1')
        monkeypatch.setattr('codeloader.CodeLoader', mock_loader)

        run_code()
        
        assert mock_instance.run_command.call_count == 2

    def test_run_code_closes_connection(self, monkeypatch):
        """Test UART connection is closed after execution."""
        mock_loader = MagicMock()
        mock_instance = MagicMock()
        # First call checks for entry.sh existence
        mock_instance.run_command.side_effect = [
            ("exists", 0),  # entry.sh exists
            ("output", 0),  # entry.sh runs
        ]
        mock_instance.fd = 123  # Simulate open file descriptor
        
        # Track close() calls on the mock instance
        close_call_tracker = []
        def track_close():
            close_call_tracker.append(True)
            mock_instance.fd = None
        
        mock_instance.close = MagicMock(side_effect=track_close)
        
        mock_loader.return_value = mock_instance
        
        monkeypatch.setenv('SIMULATED_ENV', '1')
        monkeypatch.setattr('codeloader.CodeLoader', mock_loader)

        run_code()
        
        # loader.close() should have been called in the finally block
        assert len(close_call_tracker) == 1
        # The fd should be closed (set to None) in close() method
        assert mock_instance.fd is None
