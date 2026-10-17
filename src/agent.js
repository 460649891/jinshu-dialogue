'use strict';
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
    let sequence=0;
    function readString(object, maximum=65536) {
        const length=object.add(4).readU32();
        if(length>maximum) throw new Error('对白字符串长度异常');
        return length ? Array.from(new Uint8Array(object.readPointer().readByteArray(length))) : [];
    }
    function readSpeaker(owner) {
        const layout=profile.snapshot;
        const role=owner.add(layout.role_offset).readS32();
        if(role<0) return [];
        const count=main.base.add(layout.role_count_rva).readU16();
        if(role>=count) throw new Error('对白人物编号超出适配范围：' + role + '/' + count);
        const flag=main.base.add(layout.pointer_key_rva).readU8();
        if(!flag) throw new Error('人物数据尚未初始化');
        const key=(flag ^ 0x6d)*0x01010101;
        const table=main.base.add(layout.role_table_rva).readPointer();
        const roleAddress=ptr((table.add(role*4).readU32() ^ key) >>> 0);
        const decodeBase=main.base.add(layout.decode_table_rva).readPointer();
        const decodeOffset=main.base.add(layout.decode_offset_rva).readU32();
        const name=[];
        for(let i=0;i<layout.name_max_bytes;i++) {
            const address=roleAddress.add(layout.name_offset+i);
            const page=ptr((address.toUInt32() & 0xfffffe00) >>> 0);
            const index=page.add(4).readU8()+decodeOffset;
            const decoded=decodeBase.add(index*256+address.readU8()).readU8();
            if(!decoded) break;
            name.push(decoded);
        }
        return name;
    }
    // The game updates the role before replacing the body and can draw in
    // between. Capture only after the assignment returns, while this game
    // thread is paused in the hook. No name/body caches or paint ordering.
    Interceptor.attach(main.base.add(profile.assign_rva), {
        onEnter() {
            if(this.returnAddress.sub(main.base).toUInt32()===profile.commit_rva) {
                this.owner=this.context.ecx.sub(profile.snapshot.body_offset);
            }
        },
        onLeave() {
            if(!this.owner) return;
            const owner=this.owner;
            const text=readString(owner.add(profile.snapshot.body_offset));
            if(!text.length) return;
            const speaker=readSpeaker(owner);
            send({event:'dialogue', sequence:++sequence, speaker, text});
        }
    });
    send({event:'ready',path:main.path,arch:Process.arch});
}
