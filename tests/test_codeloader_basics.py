#!/usr/bin/env python3
################################################################################
# Tests for the CodeLoader class basic functionality.
#
# These tests verify the UART communication layer including:
# - Prompt stripping
# - Command execution
# - File upload
# - Directory removal
################################################################################

import os
import sys
import time
import pytest

# Add parent directory to path so we can import codeloader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import codeloader


###############
# TestPromptStripping
#
# Tests for the _strip_prompt method which removes bash prompt prefixes
# from command output lines.
###############

class TestPromptStripping:
    """Tests for CodeLoader._strip_prompt()."""

    def test_strip_user_host_prompt(self):
        """Test stripping user@host:dir$ prompt."""
        loader = codeloader.CodeLoader.__new__(codeloader.CodeLoader)
        # Should strip "user@host:/home$ " prefix
        result = loader._strip_prompt("user@host:/home$ echo hello")
        assert "echo hello" in result
        assert "user@host" not in result

    def test_strip_tilde_prompt(self):
        """Test stripping ~$ prompt."""
        loader = codeloader.CodeLoader.__new__(codeloader.CodeLoader)
        result = loader._strip_prompt("~$ echo hello")
        assert "echo hello" in result
        assert "~$" not in result

    def test_strip_prompt_only(self):
        """Test that prompt-only lines are emptied."""
        loader = codeloader.CodeLoader.__new__(codeloader.CodeLoader)
        result = loader._strip_prompt("$")
        assert result == ''

    def test_strip_hash_prompt(self):
        """Test stripping # prompt (root user)."""
        loader = codeloader.CodeLoader.__new__(codeloader.CodeLoader)
        result = loader._strip_prompt("# echo hello")
        assert "echo hello" in result

    def test_no_prompt(self):
        """Test that lines without prompts are unchanged."""
        loader = codeloader.CodeLoader.__new__(codeloader.CodeLoader)
        result = loader._strip_prompt("just normal output")
        assert result == "just normal output"


###############
# TestCodeLoaderConnection
#
# Tests for CodeLoader initialization and connection handling.
# These tests require the simulated UART interface.
###############

class TestCodeLoaderConnection:
    """Tests for CodeLoader connection and basic I/O."""

    def test_connect_to_uart(self, uart_port):
        """Test that CodeLoader can connect to the UART port."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            assert loader.fd is not None
            assert loader.port == uart_port
        finally:
            loader.close()

    def test_close_closes_fd(self, uart_port):
        """Test that close() properly closes the file descriptor."""
        loader = codeloader.CodeLoader(uart_port)
        fd_before = loader.fd
        loader.close()
        assert loader.fd is None

    def test_drain_clears_buffer(self, uart_port):
        """Test that _drain() clears the input buffer."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            # This should not raise an exception
            loader._drain()
        finally:
            loader.close()


###############
# TestRunCommand
#
# Tests for the run_command method which executes shell commands
# over the UART connection and returns output and exit code.
###############

class TestRunCommand:
    """Tests for CodeLoader.run_command()."""

    def test_echo_command(self, uart_port):
        """Test running a simple echo command."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            output, exit_code = loader.run_command('echo "hello world"', timeout=10)
            assert exit_code == 0
            assert "hello world" in output
        finally:
            loader.close()

    def test_command_with_nonzero_exit(self, uart_port):
        """Test that non-zero exit codes are captured correctly."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            output, exit_code = loader.run_command('false', timeout=10)
            assert exit_code == 1
        finally:
            loader.close()

    def test_command_with_custom_exit_code(self, uart_port):
        """Test that custom exit codes are captured correctly.
        
        Note: Using 'return 42' in a function or a command that exits with
        a specific code, since 'exit 42' kills the shell entirely.
        """
        loader = codeloader.CodeLoader(uart_port)
        try:
            # Use a command that returns non-zero without killing the shell
            output, exit_code = loader.run_command('(exit 42)', timeout=10)
            assert exit_code == 42
        finally:
            loader.close()

    def test_multi_line_output(self, uart_port):
        """Test that multi-line output is captured correctly."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            output, exit_code = loader.run_command(
                'echo "line1" && echo "line2" && echo "line3"',
                timeout=10
            )
            assert exit_code == 0
            assert "line1" in output
            assert "line2" in output
            assert "line3" in output
        finally:
            loader.close()

    def test_whoami_command(self, uart_port):
        """Test running whoami command."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            output, exit_code = loader.run_command('whoami', timeout=10)
            assert exit_code == 0
            # In simulated env, bash runs with env -i, so user might be "root" or similar
            assert len(output.strip()) > 0
        finally:
            loader.close()

    def test_pwd_command(self, uart_port):
        """Test running pwd command."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            output, exit_code = loader.run_command('pwd', timeout=10)
            assert exit_code == 0
            # Should return some path
            assert len(output.strip()) > 0
        finally:
            loader.close()

    def test_date_command(self, uart_port):
        """Test running date command."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            output, exit_code = loader.run_command('date', timeout=10)
            assert exit_code == 0
            assert len(output.strip()) > 0
        finally:
            loader.close()

    def test_env_command(self, uart_port):
        """Test running env command."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            output, exit_code = loader.run_command('env', timeout=10)
            assert exit_code is not None
        finally:
            loader.close()


###############
# TestFileUpload
#
# Tests for the upload_file method which uploads files using base64
# encoding over the UART connection.
###############

class TestFileUpload:
    """Tests for CodeLoader.upload_file()."""

    def test_upload_small_file(self, uart_port, temp_test_file):
        """Test uploading a small text file."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            remote_path = '/tmp/test_upload_small.txt'
            result = loader.upload_file(temp_test_file, remote_path, timeout=30)
            # Should return ls output
            assert result is not None
        finally:
            loader.close()

    def test_upload_file_content_verification(self, uart_port, temp_test_file):
        """Test that uploaded file content matches original."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            remote_path = '/tmp/test_upload_verify.txt'
            loader.upload_file(temp_test_file, remote_path, timeout=30)

            # Read back the content
            output, exit_code = loader.run_command(f'cat {remote_path}', timeout=10)
            assert exit_code == 0
            assert "Hello, World!" in output
        finally:
            loader.close()

    def test_upload_nonexistent_file_raises(self, uart_port):
        """Test that uploading a nonexistent file raises an error."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            with pytest.raises(FileNotFoundError):
                loader.upload_file('/tmp/nonexistent_file_12345.txt', '/tmp/dest.txt')
        finally:
            loader.close()


###############
# TestRemoveRemoteDir
#
# Tests for the remove_remote_dir method.
###############

class TestRemoveRemoteDir:
    """Tests for CodeLoader.remove_remote_dir()."""

    def test_remove_directory(self, uart_port):
        """Test removing a directory on the remote."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            # Create a test directory first
            loader.run_command('mkdir -p /tmp/test_dir_to_remove', timeout=5)

            # Remove it
            output, exit_code = loader.remove_remote_dir('/tmp/test_dir_to_remove')

            # Verify it's gone
            check_output, check_code = loader.run_command(
                'test -d /tmp/test_dir_to_remove && echo "exists"',
                timeout=5
            )
            assert "exists" not in check_output
        finally:
            loader.close()

    def test_remove_nonexistent_directory(self, uart_port):
        """Test removing a nonexistent directory (should not fail)."""
        loader = codeloader.CodeLoader(uart_port)
        try:
            # rm -rf should not fail on nonexistent paths
            output, exit_code = loader.remove_remote_dir('/tmp/nonexistent_dir_12345')
            # Should complete without error (rm -rf is silent on missing)
        finally:
            loader.close()
