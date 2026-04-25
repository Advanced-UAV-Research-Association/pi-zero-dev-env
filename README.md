# Pi Zero 2W Development Environment

A development environment for easily uploading and running code on a Raspberry Pi Zero 2W.

## Overview

The Raspberry Pi Zero 2W runs a full Linux distribution, which makes deploying and running code significantly more involved than with microcontroller boards like Arduino. There's no simple "upload" button — you need to transfer files, set up execution environments, and manage remote processes manually.

This project solves that problem by providing a streamlined workflow for uploading code and running it on the Pi over a UART serial connection.

## How It Works

The tool connects to the Pi Zero 2W through a **UART shell interface** via a USB-to-UART adapter. Once connected, it:

1. Compresses your local `./bin` directory into a `bin.tar.gz` archive
2. Uploads the archive to the remote Pi using base64-encoded file transfer over the shell
3. Extracts and deploys the files to the remote `/app` directory
4. Executes the remote entry script (`entry.sh`) and captures the output and exit code

All UART communication, prompt stripping, and file integrity verification (via SHA256 hashing) is handled automatically.

## Quick Start

### Simulated Environment (DevContainer)

This project includes a **devcontainer** that simulates a real UART environment, allowing you to develop, test, and iterate on your code without needing the physical Pi Zero 2W connected.

Set `SIMULATED_ENV=1` in your environment to use the simulated UART port (`/tmp/ttyUART0`):

```bash
export SIMULATED_ENV=1
python3 codeloader.py
```

### Real Hardware

When connected to the physical Pi Zero 2W via USB-to-UART adapter, the tool will automatically discover the UART port and use the real remote paths:

```bash
python3 codeloader.py
```

## Project Structure

| Path | Description |
|------|-------------|
| [`codeloader.py`](codeloader.py) | Core module with `CodeLoader` class and CLI functions |
| [`tests/test_codeloader.py`](tests/test_codeloader.py) | Pytest unit tests for all codeloader functionality |
| [`bin/entry.sh`](bin/entry.sh) | Remote entry script executed on the Pi after deployment |

## Configuration

The tool supports two environments via the `SIMULATED_ENV` environment variable:

| Variable | Value | UART Port | Remote App Dir |
|----------|-------|-----------|----------------|
| `SIMULATED_ENV` | `1` | `/tmp/ttyUART0` | `/tmp/app` |
| *(unset)* | — | Discovered automatically (defaults to constant atm) | `/app` |

## Testing

Run the test suite against the simulated UART environment:

```bash
export SIMULATED_ENV=1
pytest tests/
```

## Architecture

The `CodeLoader` class manages the UART connection using raw PTY file descriptors:

- **Prompt stripping**: Automatically removes bash prompt prefixes from output
- **Command execution**: Sends commands with unique markers to reliably capture output and exit codes
- **File upload**: Uses base64-encoded heredocs for reliable file transfer
- **Integrity verification**: Compares SHA256 hashes locally and remotely after upload
