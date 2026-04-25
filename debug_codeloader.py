#!/usr/bin/env python3
################################################################################
# Diagnostic test for codeloader.py failures
#
# Tests the 4 failing scenarios with detailed logging:
# 1. strip_prompt('$ hello') and strip_prompt('# hello')
# 2. run_command with non-existent command (exit code)
# 3. uploaded file content matching
################################################################################

import os
import sys
import tempfile

os.environ['SIMULATED_ENV'] = '1'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from codeloader import CodeLoader, SIMULATED_UART_PORT, _PROMPT_PREFIX_RE, _PROMPT_ONLY_RE

################################################################################
# Diagnostic 1: Prompt stripping edge cases
################################################################################

def diagnose_prompt_stripping():
    """Diagnose why '$ hello' and '# hello' aren't stripped."""
    print("\n" + "=" * 60)
    print("DIAGNOSTIC 1: Prompt Stripping Edge Cases")
    print("=" * 60)

    loader = CodeLoader(SIMULATED_UART_PORT)

    # Show the regex patterns
    print(f"\nPROMPT_PREFIX_RE pattern: {_PROMPT_PREFIX_RE.pattern}")
    print(f"PROMPT_ONLY_RE pattern: {_PROMPT_ONLY_RE.pattern}")

    # Test cases that fail - use module-level function via re
    test_cases = ['hello', '$ hello', '# hello', '$ ', '# ', '$', '#']
    print("\nTesting _strip_prompt (standalone):")
    for case in test_cases:
        line = _PROMPT_PREFIX_RE.sub('', case)
        if _PROMPT_ONLY_RE.match(line):
            result = ''
        else:
            result = line
        print(f"  input: '{case!r}' -> output: '{result!r}'")

    # Test what the actual shell outputs
    print("\nActual shell output for echo test:")
    output, exit_code = loader.run_command('echo "$ hello"')
    print(f"  output: {output!r}")
    print(f"  exit_code: {exit_code}")

    output, exit_code = loader.run_command('echo "# hello"')
    print(f"  output: {output!r}")
    print(f"  exit_code: {exit_code}")

    if loader.fd is not None:
        os.close(loader.fd)
        loader.fd = None

################################################################################
# Diagnostic 2: Non-existent command exit code
################################################################################

def diagnose_nonexistent_command():
    """Diagnose why nonexistent command returns exit code 0."""
    print("\n" + "=" * 60)
    print("DIAGNOSTIC 2: Non-existent Command Exit Code")
    print("=" * 60)

    loader = CodeLoader(SIMULATED_UART_PORT)

    # Test with direct shell check
    print("\nDirect shell check:")
    output, exit_code = loader.run_command('which nonexistent_command_xyz 2>&1; echo "EXIT=$?"')
    print(f"  output: {output!r}")
    print(f"  exit_code: {exit_code}")

    # Test with explicit exit code capture
    print("\nExplicit exit code capture:")
    output, exit_code = loader.run_command('nonexistent_command_xyz; echo "RESULT=$?"')
    print(f"  output: {output!r}")
    print(f"  exit_code: {exit_code}")

    # Test with command not found error
    print("\nUsing 'command' builtin:")
    output, exit_code = loader.run_command('command nonexistent_command_xyz 2>&1; echo "EXIT=$?"')
    print(f"  output: {output!r}")
    print(f"  exit_code: {exit_code}")

    # Raw command without wrapper
    print("\nSimple command (raw):")
    output, exit_code = loader.run_command('nonexistent_command_xyz')
    print(f"  output: {output!r}")
    print(f"  exit_code: {exit_code}")

    if loader.fd is not None:
        os.close(loader.fd)
        loader.fd = None

################################################################################
# Diagnostic 3: File content matching issue
################################################################################

def diagnose_file_upload():
    """Diagnose file upload content matching issue."""
    print("\n" + "=" * 60)
    print("DIAGNOSTIC 3: File Upload Content Matching")
    print("=" * 60)

    loader = CodeLoader(SIMULATED_UART_PORT)

    # Create test file
    test_content = "Hello, this is test content for upload!\nLine 2\nLine 3"
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_content)
        temp_file = f.name

    try:
        # Upload
        remote_path = '/tmp/test_diagnostic_upload.txt'
        print(f"\nUploading file: {temp_file}")
        print(f"Remote path: {remote_path}")
        print(f"Content to upload:\n{test_content}")

        loader.upload_file(temp_file, remote_path, timeout=15)

        # Check file exists
        output, exit_code = loader.run_command(f'ls -la {remote_path}')
        print(f"\nls -la output: {output!r}")
        print(f"ls -la exit_code: {exit_code}")

        # Check file content with cat
        output, exit_code = loader.run_command(f'cat {remote_path}')
        print(f"\ncat output: {output!r}")
        print(f"cat exit_code: {exit_code}")

        # Check file content with hexdump (first 200 bytes)
        output, exit_code = loader.run_command(f'xxd {remote_path} | head -20')
        print(f"\nxxd output: {output!r}")
        print(f"xxd exit_code: {exit_code}")

        # Check file content with wc
        output, exit_code = loader.run_command(f'wc -c {remote_path}')
        print(f"\nwc -c output: {output!r}")
        print(f"wc -c exit_code: {exit_code}")

        # Cleanup
        loader.run_command(f'rm -f {remote_path}')

    finally:
        os.unlink(temp_file)

    if loader.fd is not None:
        os.close(loader.fd)
        loader.fd = None

################################################################################
# Main
################################################################################

if __name__ == "__main__":
    diagnose_prompt_stripping()
    diagnose_nonexistent_command()
    diagnose_file_upload()
    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)
