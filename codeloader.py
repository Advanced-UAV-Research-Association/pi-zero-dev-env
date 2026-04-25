#!/usr/bin/env python3
################################################################################
# Code Loader CLI for uploading and running code on a Raspberry Pi board.
#
# Reference implementation: main.py
# This module provides a CLI interface for the code loader functionality.
################################################################################

import argparse
import base64
import fcntl
import hashlib
import os
import re
import sys
import tarfile
import tempfile
import time

################################################################################
# Constants
################################################################################

# Path to the temporary directory for holding the archive during upload
CODELOADER_TEMP_DIR = '/tmp/codeloader'

# Path to the local bin directory to compress
LOCAL_BIN_DIR = './bin'

# Name of the archive file
ARCHIVE_NAME = 'bin.tar.gz'

# Simulated Environment Configuration
# Used when SIMULATED_ENV=1; values imported from main.py
SIMULATED_UART_PORT = '/tmp/ttyUART0'
SIMULATED_REMOTE_APP_DIR = '/tmp/app'

# Real Environment Configuration
REAL_REMOTE_APP_DIR = '/app'

################################################################################
# UART Communication Helpers
################################################################################

# Regex patterns for stripping bash prompts from output lines.
_PROMPT_PREFIX_RE = re.compile(
    r'(?:'
    r'\S+@\S+:\S*\s*[#$]\s*'       # user@host:dir$ or user@host:dir#
    r'|\S+-\d+\.\d+[#$]\s*'         # shell-version$ or shell-version#
    r'|~[#$]\s*'                     # ~$ or ~#
    r')'
)
_PROMPT_ONLY_RE = re.compile(r'^[#$]\s*$')


class CodeLoader:
    """Handles UART serial communication with the remote board.

    Connects to a UART port, disables echo, and provides methods to
    run commands and upload files over the shell connection.
    """

    def __init__(self, port):
        self.port = port
        self.fd: int | None = None
        # Open PTY (non-blocking via fcntl after open)
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # Allow shell to settle
        time.sleep(0.3)
        self._drain()

        # Disable local echo so we don't read our own commands back
        self.run_command("stty -echo", timeout=2)
        self._drain()

    def close(self):
        """Close the UART file descriptor."""
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _drain(self):
        """Discard any buffered data."""
        assert self.fd is not None
        while True:
            try:
                chunk = os.read(self.fd, 4096)
                if not chunk:
                    break
            except (BlockingIOError, OSError):
                break

    def _strip_prompt(self, line):
        """Strip common bash prompt prefixes from an output line."""
        line = _PROMPT_PREFIX_RE.sub('', line)
        if _PROMPT_ONLY_RE.match(line):
            return ''
        return line

    def _write(self, data):
        assert self.fd is not None
        if isinstance(data, str):
            data = data.encode('utf-8')
        os.write(self.fd, data)

    def _read_until(self, marker, timeout=5):
        """Read until marker appears or timeout."""
        assert self.fd is not None
        marker_b = marker.encode()
        buf = b''
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = os.read(self.fd, 1024)
                if chunk:
                    buf += chunk
                    if marker_b in buf:
                        return buf.decode('utf-8', errors='replace')
                else:
                    time.sleep(0.01)
            except (BlockingIOError, OSError):
                time.sleep(0.01)
        return buf.decode('utf-8', errors='replace')

    def _read_all(self, timeout=1):
        """Read all available data after a quiet period."""
        assert self.fd is not None
        buf = b''
        quiet_start = None
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = os.read(self.fd, 4096)
                if chunk:
                    buf += chunk
                    quiet_start = None
                else:
                    if quiet_start is None:
                        quiet_start = time.time()
                    elif time.time() - quiet_start > 0.3:
                        break
                    time.sleep(0.01)
            except (BlockingIOError, OSError):
                if quiet_start is None:
                    quiet_start = time.time()
                elif time.time() - quiet_start > 0.3:
                    break
                time.sleep(0.01)
        return buf.decode('utf-8', errors='replace')

    def run_command(self, cmd, timeout=10, stream=False):
        """Send a command and return (output, exit_code).

        Args:
            cmd: The shell command to execute.
            timeout: Maximum time to wait for the command to complete.
            stream: If True, print output in real-time (streaming mode).

        Returns:
            tuple: (output_string, exit_code_int or None)
        """
        # Use unique markers that won't appear in normal output.
        # The exit code is written with a unique prefix so it can be
        # reliably extracted without colliding with command output.
        start_marker = "---START---"
        end_marker = "---END---"
        exit_prefix = "---EXITCODE:"

        # CRITICAL FIX: Capture $? immediately after the command, before
        # any echo statements. This ensures we get the actual command's
        # exit code, not the exit code of 'echo'.
        script = (
            f"\necho '{start_marker}'\n"
            f"({cmd}; _rc=$?; printf '\\n'; echo \"{exit_prefix}$_rc\")\n"
            f"echo '{end_marker}'\n"
        )
        self._write(script)

        if not stream:
            # Read until end marker appears
            raw = self._read_until(end_marker, timeout=timeout)
            # Allow exit code line to arrive
            time.sleep(0.1)
            raw += self._read_all(timeout=1)

            lines = raw.splitlines()
            output_lines = []
            collecting = False
            exit_code = None

            for line in lines:
                cleaned = self._strip_prompt(line)
                stripped = cleaned.strip()

                # Check for exit code line first (has unique prefix)
                if stripped.startswith(exit_prefix):
                    exit_str = stripped[len(exit_prefix):]
                    if exit_str.isdigit():
                        exit_code = int(exit_str)
                    continue

                if stripped == start_marker:
                    collecting = True
                    continue
                if stripped == end_marker:
                    collecting = False
                    continue
                if collecting:
                    output_lines.append(cleaned)

            return '\n'.join(output_lines), exit_code

        # Streaming mode: print output in real-time
        assert self.fd is not None
        buf = b''
        output_lines = []
        collecting = False
        exit_code = None
        found_end = False
        start = time.time()

        while time.time() - start < timeout:
            try:
                chunk = os.read(self.fd, 1024)
                if chunk:
                    buf += chunk
                    while b'\n' in buf:
                        line, buf = buf.split(b'\n', 1)
                        line_str = line.decode('utf-8', errors='replace').rstrip('\r')
                        # Strip bash prompt prefix
                        cleaned = self._strip_prompt(line_str)
                        stripped = cleaned.strip()

                        # Check for exit code line first (has unique prefix)
                        if stripped.startswith(exit_prefix):
                            exit_str = stripped[len(exit_prefix):]
                            if exit_str.isdigit():
                                exit_code = int(exit_str)
                            continue

                        if stripped == start_marker:
                            collecting = True
                            continue
                        if stripped == end_marker:
                            collecting = False
                            found_end = True
                            break
                        if found_end and stripped.isdigit():
                            exit_code = int(stripped)
                            found_end = False
                            continue
                        if collecting:
                            output_lines.append(cleaned)
                            print(cleaned, flush=True)
                    if found_end:
                        break
                else:
                    time.sleep(0.01)
            except (BlockingIOError, OSError):
                time.sleep(0.01)
            if found_end:
                break

        # Handle any remaining data in buffer
        if buf:
            line_str = buf.decode('utf-8', errors='replace').rstrip('\r')
            cleaned = self._strip_prompt(line_str)
            stripped = cleaned.strip()

            if stripped.startswith(exit_prefix):
                exit_str = stripped[len(exit_prefix):]
                if exit_str.isdigit():
                    exit_code = int(exit_str)
            elif stripped == start_marker:
                collecting = True
            elif stripped == end_marker:
                collecting = False
                found_end = True
            elif found_end and stripped.isdigit():
                exit_code = int(stripped)
            elif collecting and stripped:
                output_lines.append(cleaned)
                print(cleaned, flush=True)

        return '\n'.join(output_lines), exit_code

    def upload_file(self, local_path, remote_path, timeout=30):
        """Upload a file using base64 over the shell connection.

        Args:
            local_path: Path to the local file to upload.
            remote_path: Path on the remote board to save the file.
            timeout: Maximum time to wait for the upload.

        Raises:
            RuntimeError: If the upload verification fails.
        """
        with open(local_path, 'rb') as f:
            data = f.read()

        b64 = base64.b64encode(data).decode('utf-8')
        wrapped = '\n'.join(b64[i:i + 76] for i in range(0, len(b64), 76))

        heredoc = f"base64 -d > {remote_path} << 'UPLOAD_EOF'\n{wrapped}\nUPLOAD_EOF\n"
        self._write(heredoc)

        # Wait for heredoc processing
        time.sleep(1.0)

        # Drain any remaining heredoc output before verification
        self._drain()

        # Verify
        out, code = self.run_command(f"ls -l {remote_path}", timeout=5)
        if code != 0:
            raise RuntimeError(f"Upload failed for {local_path}: {out}")
        return out

    def remove_remote_dir(self, remote_path):
        """Remove a directory on the remote board.

        Args:
            remote_path: Path to the remote directory to remove.

        Returns:
            tuple: (output, exit_code) from the rm command.
        """
        print(f"[codeloader] Removing {remote_path}...")
        out, code = self.run_command(f"rm -rf {remote_path}")
        if code != 0 and code is not None:
            print(f"[codeloader] Warning: rm returned {code}: {out}")
        return out, code


def discovered_uart():
    """Discover the UART port automatically.

    TODO: Implement automatic UART port discovery.
    For now, returns a default value.

    Returns:
        str: The UART port path.
    """
    return '/dev/ttyUART0'


def get_config():
    """Get configuration based on environment.

    If the SIMULATED_ENV environment variable exists and is equal to '1',
    uses the simulated environment constants (SIMULATED_UART_PORT and
    SIMULATED_REMOTE_APP_DIR).
    Otherwise, uses REAL_REMOTE_APP_DIR for remote app dir and
    discovered_uart() for UART port.

    Returns:
        dict: Configuration dictionary with 'uart_port' and 'remote_app_dir' keys.
    """
    simulated_env = os.environ.get('SIMULATED_ENV')

    if simulated_env == '1':
        # Use simulated environment values
        return {
            'uart_port': SIMULATED_UART_PORT,
            'remote_app_dir': SIMULATED_REMOTE_APP_DIR,
        }
    else:
        # Use real environment values
        return {
            'uart_port': discovered_uart(),
            'remote_app_dir': REAL_REMOTE_APP_DIR,
        }


def compress_bin_directory(temp_dir=CODELOADER_TEMP_DIR, bin_dir=LOCAL_BIN_DIR, archive_name=ARCHIVE_NAME):
    """Compress the bin directory into a tar.gz archive in the temporary directory.

    Args:
        temp_dir: Directory to store the archive.
        bin_dir: Path to the bin directory to compress.
        archive_name: Name of the archive file.

    Returns:
        str: Path to the created archive file.

    Raises:
        OSError: If the bin directory does not exist or compression fails.
    """
    # Ensure the bin directory exists
    if not os.path.isdir(bin_dir):
        raise OSError(f"Bin directory '{bin_dir}' does not exist")

    # Create the temporary directory if it doesn't exist
    os.makedirs(temp_dir, exist_ok=True)

    archive_path = os.path.join(temp_dir, archive_name)

    # Create the tar.gz archive
    with tarfile.open(archive_path, 'w:gz') as tar:
        tar.add(bin_dir, arcname=os.path.basename(bin_dir))

    return archive_path


def get_archive_size(archive_path):
    """Get the size of the archive file in bytes.

    Args:
        archive_path: Path to the archive file.

    Returns:
        int: Size of the archive in bytes.
    """
    return os.path.getsize(archive_path)


def generate_sha256_hash(archive_path):
    """Generate a SHA256 hash of the archive file.

    Args:
        archive_path: Path to the archive file.

    Returns:
        str: Hexadecimal SHA256 hash string.
    """
    sha256_hash = hashlib.sha256()

    with open(archive_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256_hash.update(chunk)

    return sha256_hash.hexdigest()


def upload_code(archive_path=None):
    """Upload code to the board.

    Compresses the bin directory, connects to the UART device, logs in,
    removes the app directory on the remote, and prepares the archive for upload.

    Args:
        archive_path: Optional path to an existing archive file.
                      If None, a new archive will be created.

    Returns:
        str: Path to the archive file, or None if upload failed.
    """
    print("[codeloader:upload] Uploading code...")

    # Create archive if not provided
    if archive_path is None:
        archive_path = compress_bin_directory()
        print(f"[codeloader:upload] Archive created at: {archive_path}")

    archive_size = get_archive_size(archive_path)
    print(f"[codeloader:upload] Archive size: {archive_size} bytes")

    archive_hash = generate_sha256_hash(archive_path)
    print(f"[codeloader:upload] SHA256 hash: {archive_hash}")

    # Get configuration
    config = get_config()
    uart_port = config['uart_port']
    remote_app_dir = config['remote_app_dir']

    # Connect to UART device and remove remote app directory
    print(f"[codeloader] Connecting to UART port: {uart_port}")
    loader = CodeLoader(uart_port)

    try:
        # Remove the app directory on the remote
        loader.remove_remote_dir(remote_app_dir)

        # Recreate the app directory (it was just removed)
        loader.run_command(f"mkdir -p {remote_app_dir}")

        # Upload the archive to the remote target
        remote_archive_path = f"{remote_app_dir}/{ARCHIVE_NAME}"
        print(f"[codeloader:upload] Uploading {archive_path} to {remote_archive_path}...")
        loader.upload_file(archive_path, remote_archive_path)
        print(f"[codeloader:upload] Upload complete. Size: {archive_size} bytes")

        # Verify integrity by computing SHA256 on the remote target
        print("[codeloader:upload] Verifying upload integrity...")
        verify_out, verify_code = loader.run_command(f"sha256sum {remote_archive_path}")
        if verify_code != 0:
            print(f"[codeloader:upload] Failed to compute SHA256 on remote: {verify_out}")
            sys.exit(1)

        # Extract the remote hash from the sha256sum output (format: "{hash}  {filename}")
        remote_hash = verify_out.strip().split()[0]

        # Compare hashes
        if archive_hash != remote_hash:
            print(f"[codeloader:upload] Hash mismatch! Local: {archive_hash}, Remote: {remote_hash}")
            sys.exit(1)

        print(f"[codeloader:upload] Integrity verified. SHA256 hash: {archive_hash}")

        # Extract the archive to the remote app directory
        print(f"[codeloader:upload] Extracting archive to {remote_app_dir}...")
        extract_out, extract_code = loader.run_command(
            f"tar -xzf {remote_archive_path} -C {remote_app_dir}"
        )
        if extract_code != 0:
            print(f"[codeloader:upload] Failed to extract archive: {extract_out}")
            sys.exit(1)

        # Make entry.sh and any other scripts executable
        print(f"[codeloader:upload] Setting executable permissions on scripts...")
        chmod_out, chmod_code = loader.run_command(
            f"find {remote_app_dir} -name '*.sh' -exec chmod +x {{}} \\;"
        )
        if chmod_code != 0:
            print(f"[codeloader:upload] Failed to set executable permissions: {chmod_out}")
            sys.exit(1)

        print(f"[codeloader:upload] Extraction complete.")

    finally:
        # Close the UART connection
        if loader.fd is not None:
            os.close(loader.fd)
            loader.fd = None

    return archive_path


def run_code():
    """Run the uploaded code on the board.

    Connects to the board via UART, checks if entry.sh exists,
    and runs it with streaming output.
    """
    # Get configuration
    config = get_config()
    uart_port = config['uart_port']
    remote_app_dir = config['remote_app_dir']
    remote_entry_sh = f'{remote_app_dir}/bin/entry.sh'

    loader = None
    try:
        # Connect to the UART device
        print(f'[codeloader:run] Connecting to {uart_port}...')
        loader = CodeLoader(uart_port)

        # Check if entry.sh exists on the remote
        check_cmd = f'test -f {remote_entry_sh} && echo "exists"'
        output, exit_code = loader.run_command(check_cmd, timeout=5)

        if exit_code != 0 or 'exists' not in output:
            print(f'[codeloader:run] No code found to run at {remote_entry_sh}')
            return

        # Run entry.sh with streaming output, changing to its directory first
        entry_dir = os.path.dirname(remote_entry_sh)
        print(f'[codeloader:run] Running {remote_entry_sh} from {entry_dir}...')
        output, exit_code = loader.run_command(f"cd {entry_dir} && ./entry.sh", timeout=120, stream=True)

        # Print exit code and status
        if exit_code is not None:
            if exit_code == 0:
                print(f'\n[codeloader:run] Program exited successfully with code {exit_code}')
            else:
                print(f'\n[codeloader:run] Program exited with non-zero code {exit_code}')
        else:
            print('\n[codeloader:run] Program exited (exit code unknown)')

    except Exception as e:
        print(f'[codeloader:run] Error: {e}')
    finally:
        if loader is not None:
            loader.close()


def main():
    """Main entry point for the Code Loader CLI.

    Parses command-line arguments and executes the appropriate action:
    upload, run, or upload-and-run. Defaults to upload-and-run
    if no option is specified.
    """
    parser = argparse.ArgumentParser(description="Code Loader for Raspberry Pi board")
    parser.add_argument("--upload", action="store_true", help="Upload code to the board")
    parser.add_argument("--run", action="store_true", help="Run the uploaded code on the board")
    parser.add_argument(
        "--upload-and-run",
        action="store_true",
        help="Upload code to the board and then run it",
    )

    args = parser.parse_args()

    # Default behavior: upload-and-run if no option specified
    if not any([args.upload, args.run, args.upload_and_run]):
        args.upload_and_run = True

    if args.upload_and_run:
        print("[codeloader] Uploading and running code...")
        upload_code()
        run_code()
    elif args.upload:
        upload_code()
    elif args.run:
        run_code()


if __name__ == "__main__":
    main()
