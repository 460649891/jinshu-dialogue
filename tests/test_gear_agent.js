'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const agent=path.join(__dirname,'../src/gear_agent.js');
assert.ok(fs.existsSync(agent),'Native Gear SDK adapter is not implemented');
const code=fs.readFileSync(agent,'utf8');
function fixture(options={}) {
    let speed=options.initialSpeed||0,added=0,closed=0,writes=0,receiver;
    const sent=[];
    const mode=options.mode||'manager';
    const exe=mode==='game'?'C:\\Game\\jshyl5.exe':'C:\\Game\\biansuchilun.com\\GearNT.exe';
    const dll='C:\\Game\\biansuchilun.com\\GearNtKe.dll';
    const handle={isNull:()=>false};
    const gear={path:options.dll||dll,getExportByName:name=>name};
    const functions={
        GetSpeed:()=>speed,
        SetSpeed:value=>{speed=value;writes++;},
        AddProcess:h=>{assert.equal(h,handle);added++;return options.addFailure?0:1;},
        CloseHandle:h=>{assert.ok(h===handle||h.snapshot);closed++;return 1;},
        CreateToolhelp32Snapshot:(flags,pid)=>({snapshot:true,pid,toUInt32:()=>options.snapshotError?0xffffffff:pid+1000}),
        Module32FirstW:(h,entry)=>{entry.text=options.otherDll||dll;return (options.otherTargets||[]).includes(h.pid)?1:0;},
        Module32NextW:()=>0,
    };
    function NativeFunction(name,result,args,abi) {
        assert.equal(abi,['GetSpeed','SetSpeed','AddProcess'].includes(name)?'mscdecl':'stdcall','Windows ABI must match the native SDK');
        assert.ok(functions[name],name);
        return functions[name];
    }
    function SystemFunction(name,result,args,abi) {
        assert.equal(abi,'stdcall');
        if(name==='CreateToolhelp32Snapshot') return (...values)=>({value:functions[name](...values),lastError:options.snapshotError||0});
        if(name==='Module32FirstW'||name==='Module32NextW') return (...values)=>{
            const value=functions[name](...values);return {value,lastError:value?0:18};
        };
        if(name==='OpenProcess') return (rights,inherit,pid)=>{
            assert.equal(rights,0x43a);assert.equal(inherit,0);assert.equal(pid,7);
            return {value:handle,lastError:0};
        };
        assert.equal(name,'QueryFullProcessImageNameW');
        return (h,flags,buffer,size)=>{buffer.text=options.targetPath||'C:\\Game\\jshyl5.exe';return {value:1,lastError:0};};
    }
    const rpc={exports:{}};
    vm.runInNewContext(code,{
        GEAR_CONTEXT:{mode,executable:exe,dll_path:dll},
        Process:{arch:'ia32',mainModule:{path:options.mainPath||exe},
            getModuleByName:name=>name==='kernel32.dll'?{getExportByName:n=>n}:gear,
            findModuleByName:()=>options.noDll?null:gear},
        Memory:{alloc:()=>({text:'',writeU32(){},add(){return this;},readUtf16String(){return this.text;}})},
        NativeFunction,SystemFunction,rpc,
        recv:(type,callback)=>{receiver=callback;},send:value=>sent.push(JSON.parse(JSON.stringify(value))),
    });
    return {api:rpc.exports,results:()=>({speed,added,closed}),writes:()=>writes,
        message:(method,args)=>{receiver({id:42,method,args});return sent.pop();}};
}
let item=fixture();
assert.equal(item.api.configure(7,true,'C:\\Game\\jshyl5.exe').speed,10);
assert.deepEqual(item.results(),{speed:10,added:1,closed:1});
item=fixture();
item.api.configure(7,false,'C:\\Game\\jshyl5.exe');
assert.deepEqual(item.results(),{speed:10,added:0,closed:1},'Existing game DLL must not be injected twice');
item=fixture({targetPath:'C:\\Other\\unrelated.exe'});
assert.throws(()=>item.api.configure(7,true,'C:\\Game\\jshyl5.exe'),/路径|目标/);
assert.deepEqual(item.results(),{speed:0,added:0,closed:1},'A reused PID may not redirect injection');
item=fixture({addFailure:true});
assert.throws(()=>item.api.configure(7,true,'C:\\Game\\jshyl5.exe'),/加入|连接|注入/);
assert.equal(item.results().closed,1);
assert.throws(()=>fixture({mainPath:'C:\\Other\\GearNT.exe'}),/路径/);
item=fixture({mode:'game',noDll:true});
assert.equal(item.api.state().loaded,false);
assert.throws(()=>item.api.configure(7,true,'C:\\Game\\jshyl5.exe'),/管理|角色/);
assert.throws(()=>fixture({dll:'C:\\Other\\GearNtKe.dll'}).api.state(),/路径|目录/);
item=fixture({otherTargets:[99]});
assert.throws(()=>item.api.configure(7,true,'C:\\Game\\jshyl5.exe',[99]),/其他程序/);
assert.deepEqual(item.results(),{speed:0,added:0,closed:2},'Shared-rate conflict may not inject or change another target');
item=fixture({initialSpeed:10,otherTargets:[99]});
item.api.configure(7,true,'C:\\Game\\jshyl5.exe',[99]);
assert.equal(item.writes(),0,'Already-2x Gear may not reset the shared clock');
item=fixture({mode:'game',noDll:true});
assert.deepEqual(item.message('state',[]),{event:'gear-reply',id:42,result:{loaded:false,dll_path:null,speed:null,other_targets:[]}});
assert.match(item.message('configure',[7,true,'C:\\Game\\jshyl5.exe']) .error,/管理/);
item=fixture({snapshotError:24});
assert.throws(()=>item.api.configure(7,true,'C:\\Game\\jshyl5.exe',[99]),/快照|核实/);
assert.equal(item.writes(),0,'An uncertain module snapshot must not authorize a shared-rate change');
item=fixture({otherTargets:[99],otherDll:'C:\\Alternate\\GearNtKe.dll'});
assert.throws(()=>item.api.configure(7,true,'C:\\Game\\jshyl5.exe',[99]),/其他程序/);
assert.equal(item.writes(),0,'Another Gear DLL path must conservatively block a shared-rate change');
console.log('Gear native SDK: x86 ABI, exact process targeting, reuse, failures and handle cleanup passed.');
