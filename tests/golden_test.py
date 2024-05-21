import contextlib
import io
import logging
import os
import tempfile

import pytest
from machine import machine
from translator import translator


@pytest.mark.golden_test('golden/*.yml')
def test_translator_and_machine(golden, caplog):
    caplog.set_level(logging.DEBUG)

    with tempfile.TemporaryDirectory() as tmpdir:
        source_file = os.path.join(tmpdir, 'source.code')
        with open(source_file, 'w', encoding='utf-8') as file:
            file.write(golden['in_source'])

        input_file = os.path.join(tmpdir, 'input.txt')
        with open(input_file, 'w', encoding='utf-8') as file:
            file.write(golden['in_stdin'])

        target_file = os.path.join(tmpdir, 'target.bin')
        target_debug_file = os.path.join(tmpdir, 'target.debug')
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            translator.main(source_file, target_file, target_debug_file)
            print('============================================================')
            machine.main(target_file, input_file)

        with open(target_debug_file, encoding='utf-8') as file:
            assert file.read() == golden.out['out_code']
        assert stdout.getvalue() == golden.out['out_stdout']
        assert caplog.text == golden.out['out_log']
