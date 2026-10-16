'use strict';
function classifyRender(caller, rect) {
    if (caller === 0x3cfef && rect[0] === 25 && rect[1] === 5 && rect[2] === 640 && rect[3] === 480) return 'speaker';
    if (caller === 0x3cbe0 && rect[0] === 0 && rect[1] === 0 && rect[2] === 490 && rect[3] > 0 && rect[3] <= 240) return 'text';
    return null;
}
class DialogueTracker {
    constructor() { this.sequence = 0; this.threads = new Map(); }
    begin(thread, owner) {
        const stack = this.threads.get(thread) || [];
        stack.push({owner, sequence:++this.sequence, speaker:[], emitted:false});
        this.threads.set(thread, stack);
    }
    current(thread) { const stack=this.threads.get(thread); return stack?.[stack.length-1] || null; }
    end(thread) {
        const stack=this.threads.get(thread);
        if (stack) { stack.pop(); if (!stack.length) this.threads.delete(thread); }
    }
    name(thread, raw) { const frame=this.current(thread); if(frame) frame.speaker=raw; }
    body(thread, raw) {
        const frame=this.current(thread);
        if(!frame || frame.emitted || !raw.length) return null;
        frame.emitted=true;
        return {sequence:frame.sequence, speaker:frame.speaker, text:raw};
    }
}
if (typeof module !== 'undefined') module.exports = {classifyRender, DialogueTracker};

if (typeof Process !== 'undefined') {
    const profile = globalThis.PROFILE;
    const main = Process.getModuleByName('jshyl5.exe');
    const normalizePath = value => value.replace(/\//g, '\\').toLowerCase();
    if (Process.arch !== 'ia32' || normalizePath(main.path) !== normalizePath(profile.executable)) {
        throw new Error('游戏进程路径或架构与适配版本不一致，未安装监听。');
    }
    for (const signature of profile.signatures) {
        const actual=new Uint8Array(main.base.add(signature.rva).readByteArray(signature.bytes.length));
        if (!signature.bytes.every((byte,index)=>actual[index]===byte)) throw new Error('游戏函数签名不匹配，已停止监听。');
    }
    const tracker=new DialogueTracker();
    const drawing=new Map();
    function readString(object, maximum=65536) {
        const length=object.add(4).readU32();
        if(length>maximum) throw new Error('对白字符串长度异常');
        return length ? Array.from(new Uint8Array(object.readPointer().readByteArray(length))) : [];
    }
    // This call stays active until the player closes the dialogue. Each call
    // owns its name and identity, including identical dialogue shown later.
    Interceptor.attach(main.base.add(profile.dialogue_rva), {
        onEnter() { tracker.begin(this.threadId, this.context.ecx.toString()); },
        onLeave() { tracker.end(this.threadId); }
    });
    Interceptor.attach(main.base.add(profile.draw_rva), {
        onEnter() {
            this.key=this.threadId;
            const stack=drawing.get(this.key)||[];
            stack.push(this.context.ecx.toString()); drawing.set(this.key,stack);
        },
        onLeave() {
            const stack=drawing.get(this.key);
            stack.pop(); if(!stack.length)drawing.delete(this.key);
        }
    });
    function matches(thread) {
        const frame=tracker.current(thread), stack=drawing.get(thread);
        return frame && stack && stack[stack.length-1]===frame.owner;
    }
    Interceptor.attach(main.base.add(profile.name_render_rva), {
        onEnter(args) {
            if(this.returnAddress.sub(main.base).toUInt32()!==profile.name_caller_rva || !matches(this.threadId))return;
            tracker.name(this.threadId,readString(args[2],1024));
        }
    });
    Interceptor.attach(main.base.add(profile.body_render_rva), {
        onEnter(args) {
            if(this.returnAddress.sub(main.base).toUInt32()!==profile.body_caller_rva || !matches(this.threadId))return;
            const event=tracker.body(this.threadId,readString(args[1]));
            if(event) send({event:'dialogue', ...event});
        }
    });
    send({event:'ready',path:main.path,arch:Process.arch});
}
