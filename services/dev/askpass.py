import os
import sys

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import keyring

from backend import SERVICE,config

alias=os.environ.get('NJU_TEX_ALIAS','')
cfg=config()
project=cfg.get('tex_projects',{}).get(alias,{})
prompt=' '.join(sys.argv[1:]).lower()
if 'username' in prompt:
    value=os.environ.get('NJU_TEX_USERNAME') or project.get('username') or cfg.get('tex_account',{}).get('username')
elif 'password' in prompt:
    value=os.environ.get('NJU_TEX_SETUP_PASSWORD') or keyring.get_password(SERVICE,'tex-account') or keyring.get_password(SERVICE,'tex:'+alias)
else:
    raise SystemExit(1)
if not value:
    raise SystemExit(1)
sys.stdout.write(value+'\n')
