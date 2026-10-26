import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
COMPONENTS = {'mail':'mail','box':'workspace','table':'workspace','table-account':'workspace','table-session':'workspace',
              'git':'dev','tex':'dev','ssh':'ssh'}
PORTS = {'all':9780,'mail':9785,'box':9787,'table':9788,'ssh':9789,'git':9790,'tex':9791}


def state_dir(component):
    root = Path(os.environ.get('NJU_MCP_DATA_DIR', REPO_ROOT/'.local')).expanduser().resolve()
    path = root/component
    path.mkdir(parents=True, exist_ok=True)
    return path


def require_vault():
    import keyring
    from keyring.backends.Windows import WinVaultKeyring
    if not isinstance(keyring.get_keyring(), WinVaultKeyring):
        raise ValueError('本项目配置入口使用 Windows 凭据库；请使用当前 Windows 用户运行。')
