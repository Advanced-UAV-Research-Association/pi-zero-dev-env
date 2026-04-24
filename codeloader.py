#!/usr/bin/env python3
################################################################################
# Code Loader CLI for uploading and running code on a Raspberry Pi board.
#
# Reference implementation: main.py
# This module provides a CLI interface for the code loader functionality.
################################################################################

import argparse
import hashlib
import os
import tarfile
import tempfile

################################################################################
# Constants
################################################################################

# Path to the temporary directory for holding the archive during upload
CODELOADER_TEMP_DIR = '/tmp/codeloader'

# Path to the local bin directory to compress
LOCAL_BIN_DIR = './bin'

# Name of the archive file
ARCHIVE_NAME = 'bin.tar.gz'


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

    # prepare archive for upload actions
    archive_path = None
    if args.upload or args.upload_and_run:
        if args.upload_and_run:
            print("Uploading and running code...")
        else:
            print("Uploading code...")

        archive_path = compress_bin_directory()
        print(f"Archive created at: {archive_path}")

        archive_size = get_archive_size(archive_path)
        print(f"Archive size: {archive_size} bytes")

        archive_hash = generate_sha256_hash(archive_path)
        print(f"SHA256 hash: {archive_hash}")

        # TODO: implement upload logic using archive_path, archive_size, archive_hash

    if args.run:
        print("Running code...")
        # TODO: implement run logic
        pass

    if args.upload_and_run:
        # TODO: implement upload-and-run logic using archive_path, archive_size, archive_hash
        pass


if __name__ == "__main__":
    main()
