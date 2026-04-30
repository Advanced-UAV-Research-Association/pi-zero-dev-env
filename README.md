# Pi Zero 2W Cross-Development Environment

A tool for easily uploading and running code on a Raspberry Pi Zero 2W (or any embedded Linux system with a UART root shell) over a serial connection. The workflow mirrors the simplicity of microcontroller platforms like Arduino: write code on your host machine, upload it, and run it on the target — all through a single CLI tool.

## What It Does

The Raspberry Pi Zero 2W runs a full Linux distribution, which makes deploying and running code significantly more involved than with microcontroller boards. There's no simple "upload" button — you need to transfer files, set up execution environments, and manage remote processes manually.

This project solves that problem by providing a streamlined workflow that:

1. Packages your local [`bin/`](bin/) directory (including the required [`entry.sh`](bin/entry.sh) entrypoint script) into a compressed archive
2. Transfers the archive to the target Pi over a UART serial connection using base64-encoded file transfer
3. Extracts the archive to the remote `/app` directory
4. Executes the remote [`bin/entry.sh`](bin/entry.sh) script and streams the output back to your terminal

## How to Use

### Prerequisites

- Python 3 with dependencies installed (`pip install -r requirements.txt`)
- A USB-to-UART adapter connected to the Pi Zero 2W's UART pins (for real hardware)
- A running shell accessible over UART on the target device

### Command-Line Interface

Run the tool directly from the project root:

```bash
python3 codeloader.py [OPTIONS]
```

| Option | Description |
|--------|-------------|
| (no option) | Upload and run code (default behavior) |
| `--upload` | Only upload code to the board |
| `--run` | Only run previously uploaded code on the board |
| `--upload-and-run` | Upload code and then run it (same as default) |

### Entry Script

Your deployable code lives in the [`bin/`](bin/) directory. The tool requires an [`entry.sh`](bin/entry.sh) script at `bin/entry.sh` which serves as the entrypoint. When you run code, this script is executed on the remote device and its output is streamed back to your local terminal.

```bash
#!/bin/bash
# bin/entry.sh — your program entrypoint
echo "Hello from the Pi!"
```

### Environment Configuration

The tool supports two modes controlled by the `SIMULATED_ENV` environment variable:

| Mode | `SIMULATED_ENV` | UART Port | Remote App Directory |
|------|-----------------|-----------|---------------------|
| Simulated | `1` | `/tmp/ttyUART0` | `/tmp/app` |
| Real Hardware | (unset) | Auto-discovered | `/app` |

Set `SIMULATED_ENV=1` to use the simulated environment for development and testing without physical hardware.

## How It Works

The control flow is handled by the [`CodeLoader`](codeloader.py:60) class, which manages UART serial communication using pyserial. Here is the high-level sequence:

### Upload Flow (`--upload` or default)

1. **Compress** — The local [`bin/`](bin/) directory is compressed into a `bin.tar.gz` archive stored in `/tmp/codeloader/`
2. **Connect** — A UART connection is opened to the target device at 115200 baud. Local echo is disabled via `stty -echo`
3. **Clean** — The remote `/app` directory is removed and recreated
4. **Transfer** — The archive is uploaded using base64-encoded heredoc over the shell connection
5. **Verify** — SHA256 hashes are computed locally and remotely and compared to ensure transfer integrity
6. **Extract** — The archive is extracted to the remote `/app` directory and shell scripts are made executable
7. **Close** — The UART connection is closed after upload completes

### Run Flow (`--run` or default)

1. **Connect** — A UART connection is opened to the target device
2. **Check** — The tool verifies that `bin/entry.sh` exists at the remote `/app` path
3. **Execute** — The entry script is run with streaming output, printing each line to the local terminal in real time
4. **Report** — The exit code is captured and printed after the script completes
5. **Close** — The UART connection is closed

### UART Communication Details

The [`CodeLoader`](codeloader.py:60) class handles several challenges of serial shell communication:

- **Prompt stripping** — Bash prompt prefixes (e.g., `user@host:~$`) are automatically removed from output using regex patterns
- **Command framing** — Each command is wrapped with unique markers (`---START---` / `---END---`) and exit codes are prefixed with `---EXITCODE:` for reliable extraction
- **Non-blocking reads** — Serial reads use timeout-based polling with quiet-period detection to determine when command output is complete
- **Integrity verification** — SHA256 hash comparison between local and remote archives ensures files were transferred correctly

## Simulated Environment and Testing

### Simulated UART

The project includes a simulated UART environment for development and testing without physical hardware. The simulation uses `socat` to create a pseudo-terminal at `/tmp/ttyUART0` backed by a clean bash shell:

```bash
socat PTY,link=/tmp/ttyUART0,raw,echo=0 EXEC:"env -i bash --norc --noprofile",pty,setsid,stderr,sigint,sane
```

Start the simulation using the provided script:

```bash
bash .devcontainer/scripts/start_uart_sim.sh
```

Set `SIMULATED_ENV=1` to make the tool use the simulated port:

```bash
export SIMULATED_ENV=1
python3 codeloader.py
```

### Running Tests

The test suite uses pytest and requires the simulated UART environment:

```bash
export SIMULATED_ENV=1
pytest tests/
```

The test suite is organized into three files:

| File | Description |
|------|-------------|
| [`tests/test_codeloader_basics.py`](tests/test_codeloader_basics.py) | Tests for core [`CodeLoader`](codeloader.py:60) functionality (command execution, prompt stripping, file upload) |
| [`tests/test_codeloader_utils.py`](tests/test_codeloader_utils.py) | Tests for utility functions (compression, hashing, configuration) |
| [`tests/test_codeloader_integration.py`](tests/test_codeloader_integration.py) | End-to-end integration tests for upload and run workflows |

Test fixtures in [`tests/conftest.py`](tests/conftest.py) manage the UART simulation lifecycle, ensuring it is running before tests execute and setting the `SIMULATED_ENV` variable automatically.

## Project Structure

| Path | Description |
|------|-------------|
| [`codeloader.py`](codeloader.py) | Core module with [`CodeLoader`](codeloader.py:60) class and CLI entry point |
| [`bin/entry.sh`](bin/entry.sh) | Remote entrypoint script executed on the target after deployment |
| [`tests/`](tests/) | Pytest test suite for all codeloader functionality |
| [`tests/conftest.py`](tests/conftest.py) | Pytest fixtures and UART simulation management |
| [`.devcontainer/`](.devcontainer/) | DevContainer configuration with UART simulation scripts |
| [`requirements.txt`](requirements.txt) | Python dependencies |
