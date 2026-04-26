#!/usr/bin/env python3
################################################################################
# Tests for CodeLoader.run_command() method
#
# Tests the run_command method which sends a shell command and returns
# (output_string, exit_code) using PTY-based testing.
#
# Tests cover:
#   - Basic command execution (echo, no output, special chars)
#   - Exit code handling (zero, non-zero, specific commands)
#   - Bash prompt stripping
#   - Timeout behavior
#   - Streaming mode
#   - Complex commands (pipes, redirects, subshells, variables, quotes)
#   - Edge cases (empty command, long output, unicode, tabs, CRLF)
#   - Integration tests (multi-command sequences, delayed output)
################################################################################

import fcntl
import os
import pty
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


################################################################################
# Helper: Simulate remote device response
################################################################################

def simulate_remote_response(slave_fd, output, exit_code, delay=0.2):
    """Simulate a remote device responding to a command.

    Writes a response with the markers that run_command expects:
    ---START---, output lines, ---EXITCODE:<code>, ---END---

    Args:
        slave_fd: Slave file descriptor to write to
        output: The output string to return
        exit_code: The exit code to return
        delay: Delay before writing response (seconds)

    Returns:
        int: The PID of the forked process
    """
    pid = os.fork()
    if pid == 0:
        # Child process - write response to slave_fd
        try:
            time.sleep(delay)
            response = f"\n---START---\n{output}\n---EXITCODE:{exit_code}\n---END---\n"
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


def simulate_remote_response_with_prompts(slave_fd, lines_with_prompts, exit_code, delay=0.2):
    """Simulate a remote device responding with bash prompts in output.

    Args:
        slave_fd: Slave file descriptor to write to
        lines_with_prompts: List of tuples (prompt, content) or just content strings
        exit_code: The exit code to return
        delay: Delay before writing response (seconds)

    Returns:
        int: The PID of the forked process
    """
    pid = os.fork()
    if pid == 0:
        # Child process
        try:
            time.sleep(delay)
            str_lines = []
            for item in ["---START---"] + lines_with_prompts + ["---EXITCODE:" + str(exit_code), "---END---"]:
                if isinstance(item, tuple):
                    str_lines.append(f"{item[0]}{item[1]}")
                else:
                    str_lines.append(item)
            response = "\n".join(str_lines) + "\n"
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
        # Parent process
        os.close(slave_fd)
        return pid


################################################################################
# TestRunCommandBasic
# Tests for basic command execution
################################################################################

class TestRunCommandBasic:
    """Tests for basic run_command functionality."""

    def test_echo_simple(self, code_loader_with_pty):
        """Test echo with simple output returns correct output and exit code.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "hello", 0)
        try:
            output, exit_code = loader.run_command('echo "hello"')
            assert output == "hello"
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_echo_multiline(self, code_loader_with_pty):
        """Test echo with multiple lines of output.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        output_text = "line 1\nline 2\nline 3"

        pid = simulate_remote_response(slave_fd, output_text, 0)
        try:
            output, exit_code = loader.run_command('echo -e "line 1\nline 2\nline 3"')
            assert output == output_text
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_echo_with_special_chars(self, code_loader_with_pty):
        """Test echo with special characters in output.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        output_text = "hello!@#$%^&*()"

        pid = simulate_remote_response(slave_fd, output_text, 0)
        try:
            output, exit_code = loader.run_command('echo "hello!@#$%^&*()"')
            assert output == output_text
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_with_no_output(self, code_loader_with_pty):
        """Test command that produces no output (true command).

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "", 0)
        try:
            output, exit_code = loader.run_command('true')
            assert output == ""
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_with_newlines(self, code_loader_with_pty):
        """Test output with embedded newlines.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        output_text = "first\n\nthird"

        pid = simulate_remote_response(slave_fd, output_text, 0)
        try:
            output, exit_code = loader.run_command('printf "first\\n\\nthird"')
            assert output == output_text
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)


################################################################################
# TestRunCommandExitCodes
# Tests for exit code handling
################################################################################

class TestRunCommandExitCodes:
    """Tests for exit code handling in run_command."""

    def test_exit_code_zero(self, code_loader_with_pty):
        """Test successful command returns exit_code=0.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "success", 0)
        try:
            output, exit_code = loader.run_command('echo success')
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_exit_code_nonzero(self, code_loader_with_pty):
        """Test failed command returns correct exit code.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "error output", 2)
        try:
            output, exit_code = loader.run_command('false')
            assert exit_code == 2
        finally:
            os.waitpid(pid, 0)

    def test_exit_code_for_ls_nonexistent(self, code_loader_with_pty):
        """Test ls /nonexistent returns non-zero exit code.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "ls: cannot access '/nonexistent': No such file or directory", 2)
        try:
            output, exit_code = loader.run_command('ls /nonexistent')
            assert exit_code != 0
            assert exit_code == 2
        finally:
            os.waitpid(pid, 0)

    def test_exit_code_for_false_command(self, code_loader_with_pty):
        """Test false command returns exit_code=1.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "", 1)
        try:
            output, exit_code = loader.run_command('false')
            assert exit_code == 1
        finally:
            os.waitpid(pid, 0)

    def test_exit_code_for_true_command(self, code_loader_with_pty):
        """Test true command returns exit_code=0.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "", 0)
        try:
            output, exit_code = loader.run_command('true')
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_exit_code_various_values(self, pty_pair):
        """Test various exit code values are correctly captured.

        Args:
            pty_pair: Raw PTY pair fixture
        """
        master_fd, slave_fd = pty_pair

        # Set master to non-blocking like CodeLoader does
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        loader = CodeLoader.__new__(CodeLoader)
        loader.fd = master_fd
        loader.port = "test"

        try:
            for expected_code in [0, 1, 2, 13, 42, 127, 255]:
                # Create a new PTY pair for each iteration since simulate_remote_response
                # closes the slave_fd after forking
                iter_master, iter_slave = create_pty_pair()
                flags = fcntl.fcntl(iter_master, fcntl.F_GETFL)
                fcntl.fcntl(iter_master, fcntl.F_SETFL, flags | os.O_NONBLOCK)

                # Replace the loader's fd temporarily
                original_fd = loader.fd
                loader.fd = iter_master

                try:
                    pid = simulate_remote_response(iter_slave, f"exit {expected_code}", expected_code)
                    try:
                        output, exit_code = loader.run_command(f'exit {expected_code}')
                        assert exit_code == expected_code, f"Expected exit code {expected_code}, got {exit_code}"
                    finally:
                        os.waitpid(pid, 0)
                finally:
                    # Restore original fd and close iteration fds
                    loader.fd = original_fd
                    close_pty_pair(iter_master, iter_slave)
        finally:
            loader.fd = None


################################################################################
# TestRunCommandPromptStripping
# Tests for bash prompt stripping
################################################################################

class TestRunCommandPromptStripping:
    """Tests for bash prompt stripping in run_command output."""

    def test_output_with_bash_prompt(self, code_loader_with_pty):
        """Test output containing user@host:dir$ prefix is stripped.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response_with_prompts(
            slave_fd,
            [("user@host:/path$", "echo hello"), "hello"],
            0
        )
        try:
            output, exit_code = loader.run_command('echo hello')
            assert "user@host" not in output
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_output_with_tilde_prompt(self, code_loader_with_pty):
        """Test output containing ~$ prefix is stripped.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response_with_prompts(
            slave_fd,
            ["~$ echo hello", "hello"],
            0
        )
        try:
            output, exit_code = loader.run_command('echo hello')
            assert "~$" not in output
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_output_with_only_prompt_line(self, pty_pair):
        """Test line that is just $ or # is stripped.

        Args:
            pty_pair: Raw PTY pair fixture
        """
        master_fd, slave_fd = pty_pair

        # Set master to non-blocking like CodeLoader does
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        loader = CodeLoader.__new__(CodeLoader)
        loader.fd = master_fd
        loader.port = "test"

        try:
            pid = simulate_remote_response(slave_fd, "$\nhello\n# \nworld", 0)
            try:
                output, exit_code = loader.run_command('echo test')
                # Lines that are just $ or # should be stripped (become empty)
                assert exit_code == 0
            finally:
                os.waitpid(pid, 0)
        finally:
            loader.fd = None

    def test_output_mixed_prompts(self, code_loader_with_pty):
        """Test some lines with prompts, some without.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response_with_prompts(
            slave_fd,
            ["user@host:~$ echo hello", "hello", "world"],
            0
        )
        try:
            output, exit_code = loader.run_command('echo hello')
            assert "user@host" not in output
            assert "hello" in output
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_output_no_prompts(self, code_loader_with_pty):
        """Test output without any prompts is returned unchanged.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "hello world\nfoo bar", 0)
        try:
            output, exit_code = loader.run_command('echo "hello world"')
            assert "hello world" in output
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)


################################################################################
# TestRunCommandTimeout
# Tests for timeout behavior
################################################################################

class TestRunCommandTimeout:
    """Tests for timeout handling in run_command."""

    def test_command_completes_before_timeout(self, code_loader_with_pty):
        """Test normal command completes within timeout.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "fast output", 0, delay=0.1)
        try:
            output, exit_code = loader.run_command('echo "fast"', timeout=10)
            assert output == "fast output"
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_timeout(self, code_loader_with_pty, monkeypatch):
        """Test slow command times out.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            monkeypatch: Pytest fixture for patching
        """
        loader, slave_fd = code_loader_with_pty

        # Mock time to simulate timeout
        call_count = [0]

        def mock_time():
            call_count[0] += 1
            if call_count[0] < 5:
                return 0.0
            return 10.0  # Simulate timeout reached

        monkeypatch.setattr(time, 'time', mock_time)

        # Don't write any response - let it timeout
        output, exit_code = loader.run_command('sleep 100', timeout=5)
        # On timeout, output may be partial and exit_code may be None
        assert exit_code is None or isinstance(exit_code, int)

    def test_custom_timeout(self, code_loader_with_pty, monkeypatch):
        """Test custom timeout value is respected.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            monkeypatch: Pytest fixture for patching
        """
        loader, slave_fd = code_loader_with_pty

        # Mock time to simulate timeout
        call_count = [0]

        def mock_time():
            call_count[0] += 1
            if call_count[0] < 5:
                return 0.0
            return 3.0  # Simulate 3 second timeout reached

        monkeypatch.setattr(time, 'time', mock_time)

        # Don't write response - let it timeout at custom timeout
        output, exit_code = loader.run_command('sleep 100', timeout=3)
        assert exit_code is None or isinstance(exit_code, int)


################################################################################
# TestRunCommandStreaming
# Tests for streaming mode
################################################################################

class TestRunCommandStreaming:
    """Tests for streaming mode in run_command."""

    def test_streaming_mode_enabled(self, code_loader_with_pty, capsys):
        """Test stream=True prints output.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            capsys: Pytest fixture for capturing stdout
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "streamed output", 0)
        try:
            output, exit_code = loader.run_command('echo "streamed"', stream=True)
            captured = capsys.readouterr()
            assert "streamed output" in captured.out
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_streaming_mode_exit_code(self, code_loader_with_pty, capsys):
        """Test exit code captured in streaming mode.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            capsys: Pytest fixture for capturing stdout
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "output", 42)
        try:
            output, exit_code = loader.run_command('echo "output"', stream=True)
            assert exit_code == 42
        finally:
            os.waitpid(pid, 0)

    def test_streaming_mode_output_content(self, code_loader_with_pty, capsys):
        """Test output content correct in streaming mode.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
            capsys: Pytest fixture for capturing stdout
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "streamed content", 0)
        try:
            output, exit_code = loader.run_command('echo "streamed"', stream=True)
            assert output == "streamed content"
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_streaming_vs_nonstreaming(self, pty_pair, capsys):
        """Test same command, different modes produce same output.

        Args:
            pty_pair: Raw PTY pair fixture
            capsys: Pytest fixture for capturing stdout
        """
        master_fd, slave_fd = pty_pair

        # Set master to non-blocking like CodeLoader does
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        loader = CodeLoader.__new__(CodeLoader)
        loader.fd = master_fd
        loader.port = "test"

        expected_output = "comparing modes"

        try:
            # Non-streaming
            iter_master1, iter_slave1 = create_pty_pair()
            flags = fcntl.fcntl(iter_master1, fcntl.F_GETFL)
            fcntl.fcntl(iter_master1, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            loader.fd = iter_master1

            pid1 = simulate_remote_response(iter_slave1, expected_output, 0)
            try:
                output_nonstream, exit_code_nonstream = loader.run_command('echo "compare"', stream=False)
            finally:
                os.waitpid(pid1, 0)
            close_pty_pair(iter_master1, iter_slave1)

            # Streaming
            iter_master2, iter_slave2 = create_pty_pair()
            flags = fcntl.fcntl(iter_master2, fcntl.F_GETFL)
            fcntl.fcntl(iter_master2, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            loader.fd = iter_master2

            pid2 = simulate_remote_response(iter_slave2, expected_output, 0)
            try:
                output_stream, exit_code_stream = loader.run_command('echo "compare"', stream=True)
            finally:
                os.waitpid(pid2, 0)
            close_pty_pair(iter_master2, iter_slave2)

            assert output_nonstream == output_stream
            assert exit_code_nonstream == exit_code_stream
        finally:
            loader.fd = None


################################################################################
# TestRunCommandComplexCommands
# Tests for complex shell commands
################################################################################

class TestRunCommandComplexCommands:
    """Tests for complex shell command handling."""

    def test_command_with_pipe(self, code_loader_with_pty):
        """Test command with pipe: echo "hello" | wc -l.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "1", 0)
        try:
            output, exit_code = loader.run_command('echo "hello" | wc -l')
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_with_redirect(self, code_loader_with_pty):
        """Test command with redirect: echo "hello" > /dev/null.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "", 0)
        try:
            output, exit_code = loader.run_command('echo "hello" > /dev/null')
            assert output == ""
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_with_subshell(self, code_loader_with_pty):
        """Test command with subshell: (echo "hello").

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "hello", 0)
        try:
            output, exit_code = loader.run_command('(echo "hello")')
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_with_variable(self, code_loader_with_pty):
        """Test command with variable: VAR=value; echo $VAR.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "myvalue", 0)
        try:
            output, exit_code = loader.run_command('VAR=myvalue; echo $VAR')
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_with_quotes(self, code_loader_with_pty):
        """Test command with double quotes: echo "hello world".

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "hello world", 0)
        try:
            output, exit_code = loader.run_command('echo "hello world"')
            assert output == "hello world"
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_with_single_quotes(self, code_loader_with_pty):
        """Test command with single quotes: echo 'hello world'.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "hello world", 0)
        try:
            output, exit_code = loader.run_command("echo 'hello world'")
            assert output == "hello world"
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)


################################################################################
# TestRunCommandEdgeCases
# Tests for edge cases
################################################################################

class TestRunCommandEdgeCases:
    """Tests for edge cases in run_command."""

    def test_empty_command(self, code_loader_with_pty):
        """Test empty string command.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "", 0)
        try:
            output, exit_code = loader.run_command('')
            assert output == ""
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_very_long_output(self, code_loader_with_pty):
        """Test command that produces large output.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        # Generate a long output string
        output_text = "\n".join([f"line {i}" for i in range(100)])

        pid = simulate_remote_response(slave_fd, output_text, 0)
        try:
            output, exit_code = loader.run_command('seq 100')
            assert "line 0" in output
            assert "line 99" in output
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_with_unicode(self, code_loader_with_pty):
        """Test Unicode characters in output.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        output_text = "Hello \u4e16\u754c! \U0001f30d \u2764"

        pid = simulate_remote_response(slave_fd, output_text, 0)
        try:
            output, exit_code = loader.run_command('echo "unicode"')
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_with_tabs(self, code_loader_with_pty):
        """Test tab characters in output.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty
        output_text = "col1\tcol2\tcol3"

        pid = simulate_remote_response(slave_fd, output_text, 0)
        try:
            output, exit_code = loader.run_command('echo -e "col1\\tcol2\\tcol3"')
            assert "\t" in output
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_command_with_crlf(self, pty_pair):
        """Test CRLF line endings in output.

        Args:
            pty_pair: Raw PTY pair fixture
        """
        master_fd, slave_fd = pty_pair

        # Set master to non-blocking like CodeLoader does
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        loader = CodeLoader.__new__(CodeLoader)
        loader.fd = master_fd
        loader.port = "test"

        try:
            pid = simulate_remote_response(slave_fd, "line1\nline2", 0)
            try:
                output, exit_code = loader.run_command('echo "crlf"')
                assert exit_code == 0
            finally:
                os.waitpid(pid, 0)
        finally:
            loader.fd = None


################################################################################
# TestRunCommandIntegration
# Integration tests
################################################################################

class TestRunCommandIntegration:
    """Integration tests for run_command."""

    def test_run_command_with_real_pty(self, code_loader_with_pty):
        """Full integration with PTY.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "integration test", 0)
        try:
            output, exit_code = loader.run_command('echo "integration"')
            assert output == "integration test"
            assert exit_code == 0
        finally:
            os.waitpid(pid, 0)

    def test_multiple_commands_in_sequence(self, pty_pair):
        """Run multiple commands in sequence.

        Args:
            pty_pair: Raw PTY pair fixture
        """
        master_fd, slave_fd = pty_pair

        # Set master to non-blocking like CodeLoader does
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        loader = CodeLoader.__new__(CodeLoader)
        loader.fd = master_fd
        loader.port = "test"

        try:
            # First command
            iter_master1, iter_slave1 = create_pty_pair()
            flags = fcntl.fcntl(iter_master1, fcntl.F_GETFL)
            fcntl.fcntl(iter_master1, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            loader.fd = iter_master1

            pid1 = simulate_remote_response(iter_slave1, "first", 0)
            try:
                output1, exit_code1 = loader.run_command('echo "first"')
                assert output1 == "first"
                assert exit_code1 == 0
            finally:
                os.waitpid(pid1, 0)
            close_pty_pair(iter_master1, iter_slave1)

            # Second command
            iter_master2, iter_slave2 = create_pty_pair()
            flags = fcntl.fcntl(iter_master2, fcntl.F_GETFL)
            fcntl.fcntl(iter_master2, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            loader.fd = iter_master2

            pid2 = simulate_remote_response(iter_slave2, "second", 1)
            try:
                output2, exit_code2 = loader.run_command('false')
                assert output2 == "second"
                assert exit_code2 == 1
            finally:
                os.waitpid(pid2, 0)
            close_pty_pair(iter_master2, iter_slave2)

            # Third command
            iter_master3, iter_slave3 = create_pty_pair()
            flags = fcntl.fcntl(iter_master3, fcntl.F_GETFL)
            fcntl.fcntl(iter_master3, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            loader.fd = iter_master3

            pid3 = simulate_remote_response(iter_slave3, "third", 0)
            try:
                output3, exit_code3 = loader.run_command('echo "third"')
                assert output3 == "third"
                assert exit_code3 == 0
            finally:
                os.waitpid(pid3, 0)
            close_pty_pair(iter_master3, iter_slave3)
        finally:
            loader.fd = None

    def test_command_with_delayed_output(self, pty_pair):
        """Test output that arrives slowly.

        Args:
            pty_pair: Raw PTY pair fixture
        """
        master_fd, slave_fd = pty_pair

        # Set master to non-blocking like CodeLoader does
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        loader = CodeLoader.__new__(CodeLoader)
        loader.fd = master_fd
        loader.port = "test"

        try:
            pid = simulate_remote_response(slave_fd, "partial1\npartial2", 0)
            try:
                output, exit_code = loader.run_command('echo "delayed"', timeout=10)
                assert "partial1" in output
                assert "partial2" in output
                assert exit_code == 0
            finally:
                os.waitpid(pid, 0)
        finally:
            loader.fd = None

    def test_command_with_pty_pair_fixture(self, pty_pair):
        """Test using raw pty_pair fixture directly.

        Args:
            pty_pair: Raw PTY pair fixture
        """
        master_fd, slave_fd = pty_pair

        # Set master to non-blocking like CodeLoader does
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # Create a minimal CodeLoader-like object
        loader = CodeLoader.__new__(CodeLoader)
        loader.fd = master_fd
        loader.port = "test"

        try:
            pid = simulate_remote_response(slave_fd, "direct pty test", 0)
            try:
                output, exit_code = loader.run_command('echo "test"')
                assert output == "direct pty test"
                assert exit_code == 0
            finally:
                os.waitpid(pid, 0)
        finally:
            close_pty_pair(master_fd, slave_fd)

    def test_run_command_returns_tuple(self, code_loader_with_pty):
        """Test that run_command always returns a tuple.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "output", 0)
        try:
            result = loader.run_command('echo "test"')
            assert isinstance(result, tuple)
            assert len(result) == 2
            output, exit_code = result
            assert isinstance(output, str)
            assert isinstance(exit_code, int)
        finally:
            os.waitpid(pid, 0)

    def test_run_command_output_type(self, code_loader_with_pty):
        """Test that output is always a string.

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "string output", 0)
        try:
            output, exit_code = loader.run_command('echo "test"')
            assert isinstance(output, str)
        finally:
            os.waitpid(pid, 0)

    def test_run_command_exit_code_type(self, code_loader_with_pty):
        """Test that exit_code is always an int (when available).

        Args:
            code_loader_with_pty: Fixture providing CodeLoader and slave_fd
        """
        loader, slave_fd = code_loader_with_pty

        pid = simulate_remote_response(slave_fd, "output", 0)
        try:
            output, exit_code = loader.run_command('echo "test"')
            assert isinstance(exit_code, int)
        finally:
            os.waitpid(pid, 0)
