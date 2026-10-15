import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def protocol(data):
    for service,count in {'mail':5,'box':5,'table':6,'git':5,'tex':5,'ssh':7}.items():
        params = StdioServerParameters(command=sys.executable,args=[str(ROOT/'manage.py'),'serve',service],
                                      cwd=str(ROOT),env={'NJU_MCP_DATA_DIR':data})
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert len(tools)==count, (service,len(tools))
                name = 'nju_mail_search' if service=='mail' else 'cloud_ssh_status' if service=='ssh' else 'nju_'+service+'_status'
                response = await session.call_tool(name,{'limit':0} if service=='mail' else {})
                assert response.isError == (service=='mail')
                if service=='table':
                    result=response.structuredContent or json.loads(next(c.text for c in response.content if c.type=='text'))
                    assert not result['account_configured'] and not result['bases']
                print(f'{service}: {count} tools, clean-state protocol passed.')


def main():
    with tempfile.TemporaryDirectory() as data:
        for component in ('mail','workspace','dev','ssh'):
            env=os.environ.copy()
            env['NJU_MCP_DATA_DIR']=data
            env['PYTHONPATH']=os.pathsep.join([str(ROOT/'services'/component),str(ROOT)])
            subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'/component),'-p','test_*.py'],
                           cwd=ROOT,env=env,check=True)
        asyncio.run(protocol(data))


if __name__=='__main__':
    main()
