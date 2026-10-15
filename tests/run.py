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
from mcp.client.streamable_http import streamable_http_client
import httpx


async def protocol(data):
    individual = {}
    for service,count in {'mail':5,'box':5,'table':6,'git':5,'tex':5,'ssh':7,'all':33}.items():
        params = StdioServerParameters(command=sys.executable,args=[str(ROOT/'manage.py'),'serve',service],
                                      cwd=str(ROOT),env={'NJU_MCP_DATA_DIR':data})
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert len(tools)==count, (service,len(tools))
                if service=='all':
                    assert {t.name for t in tools}==set(individual)
                    for tool in tools:
                        assert tool.inputSchema==individual[tool.name].inputSchema
                        assert tool.annotations==individual[tool.name].annotations
                    for name in ('nju_box_status','nju_table_status','nju_git_status','nju_tex_status','cloud_ssh_status'):
                        assert not (await session.call_tool(name,{})).isError
                    assert (await session.call_tool('nju_mail_search',{'limit':0})).isError
                    print('all: 33 tools, matching schemas and annotations, all service dispatch passed.')
                    continue
                individual.update({t.name:t for t in tools})
                name = 'nju_mail_search' if service=='mail' else 'cloud_ssh_status' if service=='ssh' else 'nju_'+service+'_status'
                response = await session.call_tool(name,{'limit':0} if service=='mail' else {})
                assert response.isError == (service=='mail')
                if service=='table':
                    result=response.structuredContent or json.loads(next(c.text for c in response.content if c.type=='text'))
                    assert not result['account_configured'] and not result['bases']
                print(f'{service}: {count} tools, clean-state protocol passed.')


async def http_protocol(data):
    env=os.environ.copy()
    env['NJU_MCP_DATA_DIR']=data
    process=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'serve','all','--http'],
                             cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        async with httpx.AsyncClient(timeout=1) as client:
            for _ in range(50):
                if process.poll() is not None:
                    raise RuntimeError('Combined HTTP server exited during startup.')
                try:
                    await client.get('http://127.0.0.1:9780/mcp')
                    break
                except httpx.RequestError:
                    await asyncio.sleep(0.1)
            else:
                raise RuntimeError('Combined HTTP server startup timed out.')
        async with streamable_http_client('http://127.0.0.1:9780/mcp') as (read,write,_):
            async with ClientSession(read,write) as session:
                await session.initialize()
                assert len((await session.list_tools()).tools)==33
                assert not (await session.call_tool('nju_table_status',{})).isError
                assert not (await session.call_tool('cloud_ssh_status',{})).isError
        print('all HTTP: one endpoint, 33 tools and service calls passed.')
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main():
    with tempfile.TemporaryDirectory() as data:
        for component in ('mail','workspace','dev','ssh'):
            env=os.environ.copy()
            env['NJU_MCP_DATA_DIR']=data
            env['PYTHONPATH']=os.pathsep.join([str(ROOT/'services'/component),str(ROOT)])
            subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'/component),'-p','test_*.py'],
                           cwd=ROOT,env=env,check=True)
        asyncio.run(protocol(data))
        asyncio.run(http_protocol(data))


if __name__=='__main__':
    main()
