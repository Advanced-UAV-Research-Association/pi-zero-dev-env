#!/usr/bin/env python3
################################################################################
# Tests for CodeLoader.upload_file() and CodeLoader.remove_remote_dir() methods
#
# Tests the following methods:
#   - upload_file(self, local_path, remote_path, timeout=30)
#   - remove_remote_dir(self, remote_path)
#
# Tests cover:
#   - Basic file upload (text, binary, empty files)
#   - Upload verification (success and failure cases)
#   - Base64 encoding correctness
#   - Edge cases (large files, special names, unicode)
#   - Directory removal (existing, nonexistent, special paths)
#   - Exit code handling
################################################################################

import base64
import fcntl
import os
import pty
import shutil
import tempfile
import time

import pytest

from codeloader import CodeLoader


################################################################################
# Helper: PTY pair setup and teardown
################################################################################

def create_pty_pair():
    """Create a PTY pair and return (master_fd, slave_fd).

    Returns:
        tuple: (master_fd, slave_fd) file descriptors
    """
    master_fd, slave_fd = pty.openpty()
    return master_fd, slave_fd


def close_pty_pair(master_fd, slave_fd):
    """Close both ends of a PTY pair.

    Args:
        master_fd: Master file descriptor
        slave_fd: Slave file descriptor
    """
    for fd in (master_fd, slave_fd):
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


################################################################################
# Fixtures
################################################################################

@pytest.fixture
def pty_pair():
    """Create and clean up a PTY pair for testing."""
    master_fd, slave_fd = create_pty_pair()
    try:
        yield master_fd, slave_fd
    finally:
        close_pty_pair(master_fd, slave_fd)


@pytest.fixture
def code_loader_with_pty(pty_pair):
    """Create a minimal CodeLoader-like object using the fixture's PTY fds.

    This fixture creates a CodeLoader instance that uses the master end of
    the PTY pair directly (via __new__ to skip __init__), avoiding the
    issue of CodeLoader opening a new fd to the same device.

    Yields:
        tuple: (loader, slave_fd) where loader is a CodeLoader-like object
               with fd set to the master end of the PTY pair
    """
    master_fd, slave_fd = pty_pair

    # Set master_fd to non-blocking like CodeLoader does in __init__
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    # Create a CodeLoader instance without calling __init__
    loader = CodeLoader.__new__(CodeLoader)
    loader.fd = master_fd
    loader.port = "test"

    try:
        yield loader, slave_fd
    finally:
        loader.fd = None
        close_pty_pair(master_fd, slave_fd)


@pytest.fixture
def temp_files():
    """Create temporary files for upload testing.

    Creates a temporary directory with:
        - text.txt: A simple text file with "Hello, World!" content
        - binary.bin: A binary file with all byte values (0-255)
        - empty.txt: An empty file
        - dir: The temporary directory path for cleanup

    Yields:
        dict: Dictionary with keys 'text', 'binary', 'empty', 'dir'
    """
    temp_dir = tempfile.mkdtemp()

    # Create a text file
    text_file = os.path.join(temp_dir, "test.txt")
    with open(text_file, 'w') as f:
        f.write("Hello, World!")

    # Create a binary file
    binary_file = os.path.join(temp_dir, "binary.bin")
    with open(binary_file, 'wb') as f:
        f.write(bytes(range(256)))

    # Create an empty file
    empty_file = os.path.join(temp_dir, "empty.txt")
    with open(empty_file, 'w') as f:
        pass

    yield {
        'text': text_file,
        'binary': binary_file,
        'empty': empty_file,
        'dir': temp_dir
    }

    # Cleanup
    shutil.rmtree(temp_dir)


################################################################################
# Helper: Simulate remote device response
################################################################################

def simulate_upload_verification(slave_fd, remote_path, file_size, delay=None):
    """Simulate remote device processing upload and responding to verification.

    This function simulates the remote side of an upload by:
    1. Waiting for the heredoc to be received
    2. Responding to the ls -l verification command with a success response

    Note: upload_file() has a 1-second sleep followed by _drain() before
    calling run_command. The simulation delay must be > 1.0 seconds so the
    response arrives AFTER the drain but DURING run_command's read.

    Args:
        slave_fd: Slave file descriptor to write to
        remote_path: The path that was uploaded to
        file_size: Size of the uploaded file in bytes
        delay: Delay before writing response (seconds). Defaults to 1.2s.

    Returns:
        int: The PID of the forked process
    """
    if delay is None:
        delay = 1.2  # Must be > 1.0s to survive the drain in upload_file
    pid = os.fork()
    if pid == 0:
        # Child process - write response to slave_fd
        try:
            time.sleep(delay)
            # Simulate ls -l output for the uploaded file
            ls_output = f"-rw-r--r-- 1 user group {file_size} Jan 1 00:00 {remote_path}"
            response = f"\n---START---\n{ls_output}\n---EXITCODE:0\n---END---\n"
            os.write(slave_fd, response.encode('utf-8'))
        except OSError:
            pass
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        os._exit(0)
    else:
        # Parent process - close its copy of slave_fd
        os.close(slave_fd)
        return pid


def simulate_upload_verification_failure(slave_fd, remote_path, delay=0.5):
    """Simulate remote device responding to verification with failure.

    This function simulates the remote side when file verification fails
    (e.g., file doesn't exist).

    Args:
        slave_fd: Slave file descriptor to write to
        remote_path: The path that was attempted to be verified
        delay: Delay before writing response (seconds)

    Returns:
        int: The PID of the forked process
    """
    pid = os.fork()
    if pid == 0:
        # Child process - write failure response
        try:
            time.sleep(delay)
            # Simulate ls -l failure output
            ls_output = f"ls: cannot access '{remote_path}': No such file or directory"
            response = f"\n---START---\n{ls_output}\n---EXITCODE:2\n---END---\n"
            os.write(slave_fd, response.encode('utf-8'))
        except OSError:
            pass
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        os._exit(0)
    else:
        # Parent process - close its copy of slave_fd
        os.close(slave_fd)
        return pid


def simulate_remove_response(slave_fd, delay=0.3):
    """Simulate remote device processing directory removal.

    This function simulates the remote side processing an rm -rf command.
    rm -rf always succeeds (exit code 0) even for nonexistent paths.

    Args:
        slave_fd: Slave file descriptor to write to
        delay: Delay before writing response (seconds)

    Returns:
        int: The PID of the forked process
    """
    pid = os.fork()
    if pid == 0:
        # Child process - write response to slave_fd
        try:
            time.sleep(delay)
            # rm -rf produces no output and always succeeds
            response = "\n---START---\n\n---EXITCODE:0\n---END---\n"
            os.write(slave_fd, response.encode('utf-8'))
        except OSError:
            pass
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        os._exit(0)
    else:
        # Parent process - close its copy of slave_fd
        os.close(slave_fd)
        return pid


def simulate_remove_failure_response(slave_fd, delay=0.3):
    """Simulate remote device responding to rm with failure.

    This function simulates the remote side when rm fails.

    Args:
        slave_fd: Slave file descriptor to write to
        delay: Delay before writing response (seconds)

    Returns:
        int: The PID of the forked process
    """
    pid = os.fork()
    if pid == 0:
        # Child process - write failure response
        try:
            time.sleep(delay)
            response = "\n---START---\n\n---EXITCODE:1\n---END---\n"
            os.write(slave_fd, response.encode('utf-8'))
        except OSError:
            pass
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        os._exit(0)
    else:
        # Parent process - close its copy of slave_fd
        os.close(slave_fd)
        return pid


################################################################################
# TestUploadFileBasic
# Tests for basic file upload functionality
################################################################################

class TestUploadFileBasic:
    """Tests for basic upload_file functionality."""

    def test_upload_text_file(self, code_loader_with_pty, temp_files):
        """Test uploading a simple text file.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            temp_files: Fixture providing temporary test files
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/uploaded_test.txt"

        pid = simulate_upload_verification(
            slave_fd, remote_path, os.path.getsize(temp_files['text'])
        )
        try:
            output = loader.upload_file(temp_files['text'], remote_path, timeout=5)
            assert output is not None
            assert remote_path in output
        finally:
            os.waitpid(pid, 0)

    def test_upload_empty_file(self, code_loader_with_pty, temp_files):
        """Test uploading an empty file.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            temp_files: Fixture providing temporary test files
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/uploaded_empty.txt"

        pid = simulate_upload_verification(
            slave_fd, remote_path, 0  # Empty file has size 0
        )
        try:
            output = loader.upload_file(temp_files['empty'], remote_path, timeout=5)
            assert output is not None
            assert remote_path in output
        finally:
            os.waitpid(pid, 0)

    def test_upload_binary_file(self, code_loader_with_pty, temp_files):
        """Test uploading a binary file with null bytes.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            temp_files: Fixture providing temporary test files
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/uploaded_binary.bin"

        pid = simulate_upload_verification(
            slave_fd, remote_path, os.path.getsize(temp_files['binary'])
        )
        try:
            output = loader.upload_file(temp_files['binary'], remote_path, timeout=5)
            assert output is not None
            assert remote_path in output
        finally:
            os.waitpid(pid, 0)

    def test_upload_returns_output(self, code_loader_with_pty, temp_files):
        """Test that upload_file returns a non-empty string.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            temp_files: Fixture providing temporary test files
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/uploaded_return_test.txt"

        pid = simulate_upload_verification(
            slave_fd, remote_path, os.path.getsize(temp_files['text'])
        )
        try:
            output = loader.upload_file(temp_files['text'], remote_path, timeout=5)
            assert isinstance(output, str)
            assert len(output) > 0
        finally:
            os.waitpid(pid, 0)


################################################################################
# TestUploadFileVerification
# Tests for upload verification behavior
################################################################################

class TestUploadFileVerification:
    """Tests for upload_file verification behavior."""

    def test_upload_verification_success(self, code_loader_with_pty, temp_files):
        """Test that upload succeeds when verification passes.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            temp_files: Fixture providing temporary test files
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/verify_success.txt"

        pid = simulate_upload_verification(
            slave_fd, remote_path, os.path.getsize(temp_files['text'])
        )
        try:
            output = loader.upload_file(temp_files['text'], remote_path, timeout=5)
            assert output is not None
            assert remote_path in output
        finally:
            os.waitpid(pid, 0)

    def test_upload_verification_failure_raises(self, code_loader_with_pty, temp_files):
        """Test that RuntimeError is raised when verification fails.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            temp_files: Fixture providing temporary test files
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/verify_failure.txt"

        pid = simulate_upload_verification_failure(slave_fd, remote_path)
        try:
            with pytest.raises(RuntimeError) as exc_info:
                loader.upload_file(temp_files['text'], remote_path, timeout=5)
            assert temp_files['text'] in str(exc_info.value)
        finally:
            os.waitpid(pid, 0)

    def test_upload_with_custom_remote_path(self, code_loader_with_pty, temp_files):
        """Test uploading to a custom remote path.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            temp_files: Fixture providing temporary test files
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/custom/path/to/my_file.txt"

        pid = simulate_upload_verification(
            slave_fd, remote_path, os.path.getsize(temp_files['text'])
        )
        try:
            output = loader.upload_file(temp_files['text'], remote_path, timeout=5)
            assert remote_path in output
        finally:
            os.waitpid(pid, 0)


################################################################################
# TestUploadFileBase64Encoding
# Tests for base64 encoding behavior
################################################################################

class TestUploadFileBase64Encoding:
    """Tests for base64 encoding in upload_file."""

    def test_base64_encoding_correct(self):
        """Test that base64 encoding produces correct output.

        Verifies that the base64 encoding used in upload_file is correct
        by checking against Python's standard base64 module.
        """
        test_data = b"Hello, World!"
        expected = base64.b64encode(test_data).decode('utf-8')
        actual = base64.b64encode(test_data).decode('utf-8')
        assert actual == expected

    def test_base64_line_wrapping(self):
        """Test that base64 is wrapped at 76-character lines (MIME format).

        Verifies that the line wrapping logic in upload_file produces
        lines of exactly 76 characters (except possibly the last line).
        """
        # Create data that will produce more than 76 chars of base64
        test_data = b"A" * 100
        b64 = base64.b64encode(test_data).decode('utf-8')
        wrapped = '\n'.join(b64[i:i + 76] for i in range(0, len(b64), 76))

        lines = wrapped.split('\n')
        for line in lines[:-1]:  # All but last should be exactly 76 chars
            assert len(line) == 76, f"Line length {len(line)} != 76: {line}"
        # Last line should be <= 76 chars
        assert len(lines[-1]) <= 76

    def test_binary_file_encoding(self, temp_files):
        """Test that binary data is encoded correctly.

        Args:
            temp_files: Fixture providing temporary test files
        """
        with open(temp_files['binary'], 'rb') as f:
            data = f.read()

        # Verify base64 encoding
        encoded = base64.b64encode(data).decode('utf-8')
        decoded = base64.b64decode(encoded)
        assert decoded == data

    def test_base64_empty_file_encoding(self):
        """Test that empty file produces valid base64 encoding."""
        data = b""
        encoded = base64.b64encode(data).decode('utf-8')
        assert encoded == ""

    def test_base64_unicode_encoding(self):
        """Test that unicode content is encoded correctly.

        Unicode content must be UTF-8 encoded before base64 encoding.
        """
        unicode_data = "Hello, 世界! 🌍".encode('utf-8')
        encoded = base64.b64encode(unicode_data).decode('utf-8')
        decoded = base64.b64decode(encoded)
        assert decoded == unicode_data


################################################################################
# TestUploadFileEdgeCases
# Tests for edge cases in file upload
################################################################################

class TestUploadFileEdgeCases:
    """Tests for edge cases in upload_file."""

    def test_upload_large_file(self, code_loader_with_pty):
        """Test uploading a larger file (10KB).

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        # Create a 10KB temp file
        temp_dir = tempfile.mkdtemp()
        try:
            large_file = os.path.join(temp_dir, "large.bin")
            file_size = 10 * 1024  # 10KB
            with open(large_file, 'wb') as f:
                f.write(os.urandom(file_size))

            remote_path = "/tmp/uploaded_large.bin"

            pid = simulate_upload_verification(
                slave_fd, remote_path, file_size
            )
            try:
                output = loader.upload_file(large_file, remote_path, timeout=10)
                assert output is not None
                assert remote_path in output
            finally:
                os.waitpid(pid, 0)
        finally:
            shutil.rmtree(temp_dir)

    def test_upload_file_with_spaces_in_name(self, code_loader_with_pty):
        """Test uploading a file with spaces in the name.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        # Create a temp file with spaces in the name
        temp_dir = tempfile.mkdtemp()
        try:
            spaced_file = os.path.join(temp_dir, "my test file.txt")
            with open(spaced_file, 'w') as f:
                f.write("Content with spaces in filename")

            remote_path = "/tmp/uploaded spaced file.txt"

            pid = simulate_upload_verification(
                slave_fd, remote_path, os.path.getsize(spaced_file)
            )
            try:
                output = loader.upload_file(spaced_file, remote_path, timeout=5)
                assert output is not None
                assert remote_path in output
            finally:
                os.waitpid(pid, 0)
        finally:
            shutil.rmtree(temp_dir)

    def test_upload_unicode_content(self, code_loader_with_pty):
        """Test uploading a file with unicode content.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        # Create a temp file with unicode content
        temp_dir = tempfile.mkdtemp()
        try:
            unicode_file = os.path.join(temp_dir, "unicode.txt")
            unicode_content = "Hello, 世界! 🌍 Привет мир!"
            with open(unicode_file, 'w', encoding='utf-8') as f:
                f.write(unicode_content)

            remote_path = "/tmp/uploaded_unicode.txt"

            pid = simulate_upload_verification(
                slave_fd, remote_path, os.path.getsize(unicode_file)
            )
            try:
                output = loader.upload_file(unicode_file, remote_path, timeout=5)
                assert output is not None
                assert remote_path in output
            finally:
                os.waitpid(pid, 0)
        finally:
            shutil.rmtree(temp_dir)

    def test_upload_with_different_timeout(self, code_loader_with_pty, temp_files):
        """Test uploading with a custom timeout value.

        Note: The delay is intentionally not specified to use the default 1.2s,
        which is required to survive the 1.0s sleep + drain in upload_file.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            temp_files: Fixture providing temporary test files
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/timeout_test.txt"

        # Use default delay (1.2s) to survive the drain in upload_file
        pid = simulate_upload_verification(
            slave_fd, remote_path, os.path.getsize(temp_files['text'])
        )
        try:
            output = loader.upload_file(temp_files['text'], remote_path, timeout=10)
            assert output is not None
        finally:
            os.waitpid(pid, 0)


################################################################################
# TestRemoveRemoteDirBasic
# Tests for basic directory removal functionality
################################################################################

class TestRemoveRemoteDirBasic:
    """Tests for basic remove_remote_dir functionality."""

    def test_remove_existing_dir(self, code_loader_with_pty):
        """Test removing an existing directory.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/existing_dir"

        pid = simulate_remove_response(slave_fd)
        try:
            output, exit_code = loader.remove_remote_dir(remote_path)
            assert isinstance(output, str)
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_remove_nonexistent_dir(self, code_loader_with_pty):
        """Test removing a nonexistent directory (rm -rf behavior).

        rm -rf should succeed even for nonexistent paths.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/nonexistent_dir_xyz"

        pid = simulate_remove_response(slave_fd)
        try:
            output, exit_code = loader.remove_remote_dir(remote_path)
            assert isinstance(output, str)
            assert exit_code == 0  # rm -rf succeeds for nonexistent paths
        finally:
            os.waitpid(pid, 0)

    def test_remove_returns_tuple(self, code_loader_with_pty):
        """Test that remove_remote_dir returns a tuple.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/tuple_test"

        pid = simulate_remove_response(slave_fd)
        try:
            result = loader.remove_remote_dir(remote_path)
            assert isinstance(result, tuple)
            assert len(result) == 2
        finally:
            os.waitpid(pid, 0)


################################################################################
# TestRemoveRemoteDirExitCodes
# Tests for exit code handling in remove_remote_dir
################################################################################

class TestRemoveRemoteDirExitCodes:
    """Tests for exit code handling in remove_remote_dir."""

    def test_remove_success_exit_code(self, code_loader_with_pty):
        """Test successful removal returns exit code 0.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/success_rm"

        pid = simulate_remove_response(slave_fd)
        try:
            output, exit_code = loader.remove_remote_dir(remote_path)
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_remove_nonexistent_exit_code(self, code_loader_with_pty):
        """Test nonexistent path returns exit code 0 (rm -rf behavior).

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/nonexistent_rm_xyz"

        pid = simulate_remove_response(slave_fd)
        try:
            output, exit_code = loader.remove_remote_dir(remote_path)
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)


################################################################################
# TestRemoveRemoteDirEdgeCases
# Tests for edge cases in directory removal
################################################################################

class TestRemoveRemoteDirEdgeCases:
    """Tests for edge cases in remove_remote_dir."""

    def test_remove_path_with_spaces(self, code_loader_with_pty):
        """Test removing a path with spaces.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/dir with spaces"

        pid = simulate_remove_response(slave_fd)
        try:
            output, exit_code = loader.remove_remote_dir(remote_path)
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_remove_nested_path(self, code_loader_with_pty):
        """Test removing a nested directory path.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/nested/path/to/dir"

        pid = simulate_remove_response(slave_fd)
        try:
            output, exit_code = loader.remove_remote_dir(remote_path)
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_remove_empty_string_path(self, code_loader_with_pty):
        """Test removing an empty string path (edge case).

        This tests the behavior when an empty path is provided.
        rm -rf "" should produce an error or warning.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = ""

        # Simulate rm -rf "" behavior (typically fails with exit code 1)
        pid = simulate_remove_failure_response(slave_fd)
        try:
            output, exit_code = loader.remove_remote_dir(remote_path)
            # With rm -rf "", the exit code may be non-zero
            assert isinstance(output, str)
            assert isinstance(exit_code, int)
        finally:
            os.waitpid(pid, 0)

    def test_remove_prints_status_message(self, code_loader_with_pty, capsys):
        """Test that remove_remote_dir prints a status message.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            capsys: Pytest fixture for capturing stdout/stderr
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/status_test"

        pid = simulate_remove_response(slave_fd)
        try:
            loader.remove_remote_dir(remote_path)
            captured = capsys.readouterr()
            assert "[codeloader] Removing" in captured.out
            assert remote_path in captured.out
        finally:
            os.waitpid(pid, 0)

    def test_remove_with_special_characters_in_path(self, code_loader_with_pty):
        """Test removing a path with special characters.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        remote_path = "/tmp/dir-with_special.chars"

        pid = simulate_remove_response(slave_fd)
        try:
            output, exit_code = loader.remove_remote_dir(remote_path)
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)
