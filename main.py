#!/usr/bin/env python3
"""
MVP Code Loader for Raspberry Pi Zero 2W.
Target: simulated UART shell in devcontainer (/tmp/ttyUART0).
"""

import os
import time
import tarfile
import base64
import fcntl

# Configuration
UART_PORT = '/tmp/ttyUART0'
REMOTE_APP_DIR = '/tmp/app'
LOCAL_ARCHIVE_PATH = '/tmp/bin.tar.gz'


class CodeLoader:
    def __init__(self, port=UART_PORT):
        self.port = port
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

    def run_command(self, cmd, timeout=10):
        """Send a command and return (output, exit_code)."""
        start_marker = "---START---"
        end_marker = "---END---"

        script = f"\necho '{start_marker}'\n{cmd}\necho '{end_marker}'\necho $?\n"
        self._write(script)

        # Read until end marker appears
        raw = self._read_until(end_marker, timeout=timeout)
        # Allow exit code line to arrive
        time.sleep(0.1)
        raw += self._read_all(timeout=1)

        lines = raw.splitlines()
        output_lines = []
        collecting = False

        for line in lines:
            stripped = line.strip()
            if stripped == start_marker:
                collecting = True
                continue
            if stripped == end_marker:
                collecting = False
                continue
            if collecting:
                output_lines.append(line)

        # Extract exit code: first standalone integer after end marker
        exit_code = None
        found_end = False
        for line in lines:
            stripped = line.strip()
            if stripped == end_marker:
                found_end = True
                continue
            if found_end and stripped.isdigit():
                exit_code = int(stripped)
                break

        return '\n'.join(output_lines), exit_code

    def upload_file(self, local_path, remote_path, timeout=30):
        """Upload a file using base64 over the shell connection."""
        with open(local_path, 'rb') as f:
            data = f.read()

        b64 = base64.b64encode(data).decode('utf-8')
        # Wrap base64 for safer heredoc handling
        wrapped = '\n'.join(b64[i:i + 76] for i in range(0, len(b64), 76))

        heredoc = f"base64 -d > {remote_path} << 'UPLOAD_EOF'\n{wrapped}\nUPLOAD_EOF\n"
        self._write(heredoc)

        # Wait for heredoc processing
        time.sleep(0.5)

        # Verify
        out, code = self.run_command(f"ls -l {remote_path}", timeout=5)
        if code != 0:
            raise RuntimeError(f"Upload failed for {local_path}: {out}")
        return out

    def deploy(self, local_bin_dir='./bin', remote_app_dir=REMOTE_APP_DIR):
        """Full deploy-and-run flow."""
        archive_path = LOCAL_ARCHIVE_PATH

        # 1. Compress local bin dir
        print(f"[deploy] Creating {archive_path} from {local_bin_dir}...")
        with tarfile.open(archive_path, 'w:gz') as tar:
            tar.add(local_bin_dir, arcname='.')

        # 2. Remove remote /app
        print(f"[deploy] Removing {remote_app_dir}...")
        out, code = self.run_command(f"rm -rf {remote_app_dir}")
        if code != 0 and code is not None:
            print(f"[deploy] Warning: rm returned {code}: {out}")

        # 3. Upload archive
        remote_archive = f"/tmp/{os.path.basename(archive_path)}"
        print(f"[deploy] Uploading to {remote_archive}...")
        self.upload_file(archive_path, remote_archive)

        # 4. Extract
        print(f"[deploy] Extracting to {remote_app_dir}...")
        out, code = self.run_command(
            f"mkdir -p {remote_app_dir} && tar -xzf {remote_archive} -C {remote_app_dir}"
        )
        if code != 0:
            raise RuntimeError(f"Extract failed: {out}")

        # 5. Run entry.sh
        print(f"[deploy] Running {remote_app_dir}/entry.sh...")
        out, code = self.run_command(f"bash {remote_app_dir}/entry.sh")

        # 6. Print output
        print("[deploy] --- OUTPUT ---")
        print(out)
        print("[deploy] --- END OUTPUT ---")

        # 7. Print exit code
        print(f"[deploy] Exit code: {code}")

        return code

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


if __name__ == '__main__':
    loader = CodeLoader()
    try:
        exit_code = loader.deploy()
        if exit_code != 0:
            print(f"[main] Deployment completed with non-zero exit code: {exit_code}")
        else:
            print("[main] Deployment completed successfully.")
    except Exception as e:
        print(f"[main] Error: {e}")
        raise
    finally:
        loader.close()
