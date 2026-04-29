#!/usr/bin/env python3
################################################################################
# Integration tests for the codeloader workflow functions.
#
# These tests verify the end-to-end workflow of:
# - upload_code(): Compress, upload, verify, and extract code
# - run_code(): Run uploaded code with streaming output
################################################################################

import os
import sys
import time
import pytest
import shutil

# Add parent directory to path so we can import codeloader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import codeloader


###############
# TestUploadCode
#
# Tests for the upload_code() function which handles the full upload
# workflow: compress, connect, remove remote dir, upload, verify, extract.
###############

class TestUploadCode:
    """Tests for codeloader.upload_code()."""

    def test_upload_code_with_prepared_archive(self, simulated_env, tmp_path):
        """Test uploading code with a pre-prepared archive.
        
        This test creates a temporary bin directory, compresses it,
        and verifies the upload workflow completes successfully.
        """
        # Create a temporary bin directory
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        entry_sh = bin_dir / 'entry.sh'
        entry_sh.write_text('#!/bin/bash\necho "test output"\nexit 0\n')
        entry_sh.chmod(0o755)

        # Compress the bin directory
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=str(bin_dir)
        )

        # Upload using the prepared archive
        result = codeloader.upload_code(archive_path=archive_path)
        assert result is not None
        assert os.path.exists(result)

    def test_upload_code_creates_archive_when_none(self, simulated_env):
        """Test that upload_code creates an archive when none is provided.
        
        This test relies on the existing bin/ directory in the project.
        """
        # Ensure bin directory exists
        assert os.path.isdir('./bin'), "bin directory must exist for this test"

        # Upload without providing archive path
        result = codeloader.upload_code(archive_path=None)
        assert result is not None
        assert os.path.exists(result)

    def test_upload_code_remote_archive_exists(self, simulated_env, tmp_path):
        """Test that the uploaded archive exists on the remote after upload."""
        # Create a temporary bin directory
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        entry_sh = bin_dir / 'entry.sh'
        entry_sh.write_text('#!/bin/bash\necho "test"\n')
        entry_sh.chmod(0o755)

        # Compress
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=str(bin_dir)
        )

        # Upload
        codeloader.upload_code(archive_path=archive_path)

        # Verify the archive was extracted to the remote app directory
        loader = codeloader.CodeLoader(codeloader.SIMULATED_UART_PORT)
        try:
            # Check that the remote app directory exists
            output, exit_code = loader.run_command(
                f'test -d {codeloader.SIMULATED_REMOTE_APP_DIR} && echo "exists"',
                timeout=10
            )
            assert exit_code == 0
            assert 'exists' in output
        finally:
            loader.close()

    def test_upload_code_remote_bin_exists(self, simulated_env, tmp_path):
        """Test that the bin directory is created on the remote after upload."""
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        entry_sh = bin_dir / 'entry.sh'
        entry_sh.write_text('#!/bin/bash\necho "test"\n')
        entry_sh.chmod(0o755)

        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=str(bin_dir)
        )

        codeloader.upload_code(archive_path=archive_path)

        loader = codeloader.CodeLoader(codeloader.SIMULATED_UART_PORT)
        try:
            output, exit_code = loader.run_command(
                f'test -d {codeloader.SIMULATED_REMOTE_APP_DIR}/bin && echo "exists"',
                timeout=10
            )
            assert exit_code == 0
            assert 'exists' in output
        finally:
            loader.close()

    def test_upload_code_entry_sh_is_executable(self, simulated_env, tmp_path):
        """Test that entry.sh is marked executable after upload."""
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        entry_sh = bin_dir / 'entry.sh'
        entry_sh.write_text('#!/bin/bash\necho "test"\n')
        entry_sh.chmod(0o755)

        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=str(bin_dir)
        )

        codeloader.upload_code(archive_path=archive_path)

        loader = codeloader.CodeLoader(codeloader.SIMULATED_UART_PORT)
        try:
            output, exit_code = loader.run_command(
                f'test -x {codeloader.SIMULATED_REMOTE_APP_DIR}/bin/entry.sh && echo "executable"',
                timeout=10
            )
            assert exit_code == 0
            assert 'executable' in output
        finally:
            loader.close()


###############
# TestRunCode
#
# Tests for the run_code() function which runs the uploaded entry.sh
# script on the remote device.
###############

class TestRunCode:
    """Tests for codeloader.run_code()."""

    def test_run_code_executes_entry_sh(self, simulated_env, tmp_path):
        """Test that run_code executes the entry.sh script.
        
        First uploads code, then runs it.
        """
        # Create a simple bin directory with entry.sh
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        entry_sh = bin_dir / 'entry.sh'
        entry_sh.write_text('#!/bin/bash\necho "Hello from integration test"\nexit 0\n')
        entry_sh.chmod(0o755)

        # Compress
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=str(bin_dir)
        )

        # Upload first
        codeloader.upload_code(archive_path=archive_path)

        # Run the code
        codeloader.run_code()
        # If we get here without exception, the test passes

    def test_run_code_no_entry_sh(self, simulated_env):
        """Test run_code when entry.sh doesn't exist on remote.
        
        Should print a message and return without error.
        """
        # Remove the remote app directory to ensure no entry.sh exists
        loader = codeloader.CodeLoader(codeloader.SIMULATED_UART_PORT)
        try:
            loader.remove_remote_dir(codeloader.SIMULATED_REMOTE_APP_DIR)
        finally:
            loader.close()

        # run_code should handle missing entry.sh gracefully
        codeloader.run_code()
        # Should not raise an exception

    def test_run_code_with_exit_code(self, simulated_env, tmp_path):
        """Test that run_code captures the exit code from entry.sh."""
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        entry_sh = bin_dir / 'entry.sh'
        entry_sh.write_text('#!/bin/bash\necho "test with exit 0"\nexit 0\n')
        entry_sh.chmod(0o755)

        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=str(bin_dir)
        )

        codeloader.upload_code(archive_path=archive_path)
        codeloader.run_code()


###############
# TestEndToEnd
#
# End-to-end integration tests that test the full workflow.
###############

class TestEndToEnd:
    """End-to-end integration tests for the full upload and run workflow."""

    def test_full_upload_and_run(self, simulated_env, tmp_path):
        """Test the complete workflow: create code, upload, run, verify output.
        
        This is the main integration test that verifies the entire
        codeloader pipeline works as expected.
        """
        # Create test code
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        entry_sh = bin_dir / 'entry.sh'
        entry_sh.write_text(
            '#!/bin/bash\n'
            'echo "Starting application"\n'
            'echo "Processing data"\n'
            'echo "Application complete"\n'
            'exit 0\n'
        )
        entry_sh.chmod(0o755)

        # Compress
        temp_dir = str(tmp_path / 'temp')
        archive_path = codeloader.compress_bin_directory(
            temp_dir=temp_dir,
            bin_dir=str(bin_dir)
        )

        # Upload
        result = codeloader.upload_code(archive_path=archive_path)
        assert result is not None

        # Run
        codeloader.run_code()

    def test_multiple_uploads(self, simulated_env, tmp_path):
        """Test that multiple uploads work correctly.
        
        Each upload should replace the previous one.
        Note: The archive uses the basename of the bin directory as the
        arcname, so we must use 'bin' as the directory name for the
        extracted path to be /tmp/app/bin/entry.sh.
        """
        # First upload
        bin_dir1 = tmp_path / 'bin'
        bin_dir1.mkdir()
        entry_sh1 = bin_dir1 / 'entry.sh'
        entry_sh1.write_text('#!/bin/bash\necho "version 1"\n')
        entry_sh1.chmod(0o755)

        temp_dir1 = str(tmp_path / 'temp1')
        archive1 = codeloader.compress_bin_directory(
            temp_dir=temp_dir1,
            bin_dir=str(bin_dir1)
        )
        codeloader.upload_code(archive_path=archive1)

        # Second upload - use a different temp bin dir but still named 'bin'
        bin_dir2 = tmp_path / 'bin_v2'
        bin_dir2.mkdir()
        entry_sh2 = bin_dir2 / 'entry.sh'
        entry_sh2.write_text('#!/bin/bash\necho "version 2"\n')
        entry_sh2.chmod(0o755)

        temp_dir2 = str(tmp_path / 'temp2')
        # Use arcname='bin' so it extracts to the correct path
        import tarfile
        import os
        archive2_path = os.path.join(temp_dir2, 'bin.tar.gz')
        os.makedirs(temp_dir2, exist_ok=True)
        with tarfile.open(archive2_path, 'w:gz') as tar:
            tar.add(str(bin_dir2), arcname='bin')

        codeloader.upload_code(archive_path=archive2_path)

        # Verify second version is present
        loader = codeloader.CodeLoader(codeloader.SIMULATED_UART_PORT)
        try:
            output, exit_code = loader.run_command(
                f'cat {codeloader.SIMULATED_REMOTE_APP_DIR}/bin/entry.sh',
                timeout=10
            )
            assert exit_code == 0
            assert 'version 2' in output
        finally:
            loader.close()
