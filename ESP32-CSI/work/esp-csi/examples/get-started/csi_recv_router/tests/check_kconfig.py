"""Validate batch menu defaults and limits without invoking the compiler."""
import json
from pathlib import Path
import tempfile

import kconfiglib

here = Path(__file__).resolve().parent
main = here.parent / 'main/Kconfig.projbuild'
# Stay inside the known, ignored project scratch directory.
project_work = here.parents[4]
scratch = project_work / 'host-tools/kconfig-check'
scratch.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='config-', dir=scratch) as temp:
    assert Path(temp).resolve().parent == scratch.resolve()
    file = Path(temp) / 'Kconfig'
    file.write_text('config IDF_TARGET_ESP32\n    bool\n    default y\n\nsource '
                    + json.dumps(main.as_posix()) + '\n', encoding='utf-8')
    cfg = kconfiglib.Kconfig(str(file), warn=False)
    expected = {
        'CSI_BATCH_POST_ENABLED': 'y', 'CSI_BATCH_MAX_SAMPLES': '20',
        'CSI_BATCH_BUFFER_COUNT': '4', 'CSI_POST_TIMEOUT_MS': '1000',
        'CSI_BATCH_PING_HZ': '100',
        'CSI_POST_URL': 'https://example.invalid/csi', 'CSI_POST_TOKEN': '',
        'CSI_BATCH_SERIAL_OUTPUT': 'n',
    }
    for name, value in expected.items():
        assert cfg.syms[name].str_value == value, name
    header = Path(temp) / 'sdkconfig.h'
    cfg.write_autoconf(str(header))
    assert '#define CONFIG_CSI_POST_TOKEN ""' in header.read_text()
    cfg.syms['CSI_POST_TOKEN'].set_value('unit-test-token')
    assert cfg.syms['CSI_POST_TOKEN'].str_value == 'unit-test-token'
    cfg.write_autoconf(str(header))
    assert '#define CONFIG_CSI_POST_TOKEN "unit-test-token"' in header.read_text()
    cfg.syms['CSI_BATCH_MAX_SAMPLES'].set_value('400')
    assert cfg.syms['CSI_BATCH_MAX_SAMPLES'].str_value == '400'
    cfg.syms['CSI_BATCH_MAX_SAMPLES'].set_value('401')
    assert cfg.syms['CSI_BATCH_MAX_SAMPLES'].str_value == '20'
    assert 'CSI_BATCH_WINDOW_MS' not in cfg.syms
    cfg.syms['CSI_BATCH_BUFFER_COUNT'].set_value('8')
    assert cfg.syms['CSI_BATCH_BUFFER_COUNT'].str_value == '8'
    cfg.syms['CSI_BATCH_BUFFER_COUNT'].set_value('1')
    assert cfg.syms['CSI_BATCH_BUFFER_COUNT'].str_value == '4'
    cfg.syms['CSI_BATCH_POST_ENABLED'].set_value('n')
    assert cfg.syms['CSI_BATCH_POST_ENABLED'].str_value == 'n'
print('Kconfig defaults, range limits and legacy mode passed.')
