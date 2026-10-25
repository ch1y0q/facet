"""Preserve Unicode metadata across ExifTool's Windows command-line boundary."""
import subprocess
import os
import re
import tempfile


def run_exiftool_process(args, *, timeout):
    """Run one command, using UTF-8 stdin for arguments ANSI cannot carry.

    ExifTool JSON is always UTF-8. Unicode command-line values are not reliable
    on Windows, so send them in its documented -@ argument-file format. Metadata
    values with newlines use private UTF-8 value files: ExifTool's CSTR escape
    parser changes literal $/@ characters. ASCII commands retain ordinary argv.
    """
    command = list(args)
    options = dict(capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    if any(not value.isascii() for value in command[1:]):
        executable, *arguments = command
        # ExifTool requires -config to be the first actual command-line option.
        config = arguments[:2] if arguments[:1] == ['-config'] else []
        arguments = arguments[len(config):]
        command = [executable, *config, '-charset', 'filename=UTF8', '-charset', 'UTF8', '-@', '-']
        with tempfile.TemporaryDirectory(prefix='facet-exiftool-') as directory:
            lines = []
            for index, argument in enumerate(arguments):
                assignment = re.fullmatch(r'(-[-:\w]+?#?)([-+<]?=)(.*)', argument, re.DOTALL)
                if '\n' in argument or '\r' in argument:
                    if not assignment or assignment[2] == '<=':
                        raise ValueError('ExifTool filename or option contains a newline')
                    filename = os.path.join(directory, str(index))
                    descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, 'wb') as stream:
                        stream.write(assignment[3].encode('utf-8'))
                    argument = assignment[1] + assignment[2][:-1] + '<=' + filename
                elif assignment:
                    # Ordinary argfiles strip ONE space after an assignment.
                    # Supply that space explicitly to preserve the actual value.
                    argument = assignment[1] + assignment[2] + ' ' + assignment[3]
                lines.append(argument)
            options['input'] = ''.join(value + '\n' for value in lines)
            return subprocess.run(command, **options)
    return subprocess.run(command, **options)
