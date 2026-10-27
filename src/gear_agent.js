'use strict';
// GearNT 0.46's exported API uses Windows x86 cdecl, with one shared speed code:
// multiplier = 2 ** (code / 10). Code 10 is exactly 2x.
const context=globalThis.GEAR_CONTEXT;
const normalize=value=>value.replace(/\//g,'\\').replace(/^\\\\\?\\/,'').toLowerCase();
if(Process.arch!=='ia32' || normalize(Process.mainModule.path)!==normalize(context.executable)) {
    throw new Error('变速目标进程架构或路径不匹配');
}
function gearModule() {
    const module=Process.findModuleByName('GearNtKe.dll');
    if(module && normalize(module.path)!==normalize(context.dll_path)) {
        throw new Error('变速齿轮 DLL 路径与游戏目录不一致');
    }
    return module;
}
function otherTargets(pids) {
    if(!pids.length) return [];
    const kernel=Process.getModuleByName('kernel32.dll');
    const snapshot=new SystemFunction(kernel.getExportByName('CreateToolhelp32Snapshot'),'pointer',['uint','uint'],'stdcall');
    const first=new SystemFunction(kernel.getExportByName('Module32FirstW'),'int',['pointer','pointer'],'stdcall');
    const next=new SystemFunction(kernel.getExportByName('Module32NextW'),'int',['pointer','pointer'],'stdcall');
    const close=new NativeFunction(kernel.getExportByName('CloseHandle'),'int',['pointer'],'stdcall');
    const entry=Memory.alloc(1064),targets=[]; // x86 MODULEENTRY32W; szExePath starts at 544.
    for(const pid of pids) {
        let result;
        for(let attempt=0;attempt<3;attempt++) {
            result=snapshot(8,pid);
            if(result.value.toUInt32()!==0xffffffff || result.lastError!==24) break;
        }
        // x86 GearNtKe cannot be loaded into a 64-bit process. Its module
        // snapshot fails with ERROR_PARTIAL_COPY; no foreign injection occurs.
        if(result.value.toUInt32()===0xffffffff) {
            if([5,87,299,1168].includes(result.lastError)) continue; // protected, exited or x64
            throw new Error('无法核实其他进程的模块快照，未调整共享倍率');
        }
        const handle=result.value;
        try {
            entry.writeU32(1064);
            let available=first(handle,entry);
            while(available.value) {
                // Be conservative about copied/aliased DLL paths as well.
                if(normalize(entry.add(544).readUtf16String()).split('\\').pop()==='gearntke.dll') {
                    targets.push(pid);
                    break;
                }
                available=next(handle,entry);
            }
            if(!available.value && available.lastError!==18) throw new Error('无法核实其他进程的模块列表');
        } finally { close(handle); }
    }
    return targets;
}
rpc.exports={
    state(pids=[]) {
        const module=gearModule();
        const speed=module?new NativeFunction(module.getExportByName('GetSpeed'),'int',[],'mscdecl')():null;
        return {loaded:!!module,dll_path:module?.path||null,
            speed,other_targets:module && context.mode==='manager' && speed!==10?otherTargets(pids):[]};
    },
    configure(pid,attach,expectedGame,pids=[]) {
        if(context.mode!=='manager') throw new Error('只有齿轮管理进程可以加入游戏');
        const module=gearModule();
        if(!module) throw new Error('变速齿轮尚未初始化');
        const kernel=Process.getModuleByName('kernel32.dll');
        const open=new SystemFunction(kernel.getExportByName('OpenProcess'),'pointer',['uint','int','uint'],'stdcall');
        const query=new SystemFunction(kernel.getExportByName('QueryFullProcessImageNameW'),'int',
            ['pointer','uint','pointer','pointer'],'stdcall');
        const close=new NativeFunction(kernel.getExportByName('CloseHandle'),'int',['pointer'],'stdcall');
        const result=open(0x43a,0,pid);
        if(result.value.isNull()) throw new Error('无法连接游戏进程，Windows 错误 '+result.lastError);
        try {
            // Validate the opened handle, not just an earlier PID snapshot.
            const buffer=Memory.alloc(32768*2),length=Memory.alloc(4);
            length.writeU32(32768);
            const queried=query(result.value,0,buffer,length);
            if(!queried.value) throw new Error('无法确认游戏进程路径，Windows 错误 '+queried.lastError);
            if(normalize(buffer.readUtf16String())!==normalize(expectedGame)) {
                throw new Error('目标游戏进程路径已变化，已停止变速设置');
            }
            const get=new NativeFunction(module.getExportByName('GetSpeed'),'int',[],'mscdecl');
            if(get()!==10 && otherTargets(pids).length) {
                throw new Error('变速齿轮已关联其他程序，未调整共享倍率');
            }
            if(attach) {
                const add=new NativeFunction(module.getExportByName('AddProcess'),'int',['pointer'],'mscdecl');
                if(!add(result.value)) throw new Error('变速齿轮加入游戏失败');
            }
            if(get()!==10) new NativeFunction(module.getExportByName('SetSpeed'),'void',['int'],'mscdecl')(10);
            return {speed:get()};
        } finally {
            close(result.value);
        }
    }
};
// Unlike exports_sync, this transport lets the host stop waiting even if a
// third-party native function never returns. Request ids reject late replies.
if(typeof recv==='function') {
    function receive(message) {
        recv('gear-call',receive);
        try {
            if(!['state','configure'].includes(message.method)) throw new Error('未知变速接口');
            const result=rpc.exports[message.method](...message.args);
            send({event:'gear-reply',id:message.id,result});
        } catch(error) {
            send({event:'gear-reply',id:message.id,error:String(error.message||error)});
        }
    }
    recv('gear-call',receive);
}
