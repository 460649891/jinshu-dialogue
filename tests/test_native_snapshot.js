'use strict';
// Execute the production Frida agent against a process-memory boundary. This
// reproduces rapid transitions without depending on whether a frame was drawn.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const profile = JSON.parse(fs.readFileSync(require.resolve('../profiles/jshyl-5.60c.json'), 'utf8'));
const bytes = new Map(), hooks = new Map(), events = [];
class Pointer {
    constructor(value) { this.value = Number(value) >>> 0; }
    add(n) { return new Pointer(this.value + Number(n)); }
    sub(n) { return new Pointer(this.value - Number(n instanceof Pointer ? n.value : n)); }
    toUInt32() { return this.value; }
    toString() { return '0x' + this.value.toString(16); }
    isNull() { return this.value === 0; }
    readU8() { assert.ok(bytes.has(this.value), 'Unexpected memory read at ' + this); return bytes.get(this.value); }
    readU16() { return this.readU8() | (this.add(1).readU8() << 8); }
    readU32() { return (this.readU16() | (this.add(2).readU16() << 16)) >>> 0; }
    readS32() { return this.readU32() | 0; }
    readPointer() { return new Pointer(this.readU32()); }
    readByteArray(length) { return Uint8Array.from(Array.from({length}, (_, i) => this.add(i).readU8())).buffer; }
}
const write = (address, data) => data.forEach((byte, i) => bytes.set(address + i, byte));
const word = (address, value) => write(address, [value & 255, (value >>> 8) & 255, (value >>> 16) & 255, value >>> 24]);
const base = 0x400000, frame = 0x101000, owner = 0x102000, text = 0x103000;
for (const signature of profile.signatures) write(base + signature.rva, signature.bytes);
word(frame - 0x60, owner);
word(owner + 0xfc, text);
// Two encrypted role pointers and a non-identity byte substitution table.
word(base + 0x53b610, 0x200000);
write(base + 0x53b62c, [0xb0, 9]);
write(base + 0x2d1bf0, [0x7e]);
word(base + 0x2d1980, 2);
word(base + 0x5d02c8, 0x220000);
for (let i = 0; i < 256; i++) write(0x220000 + 5 * 256 + i, [i ^ 0x5a]);
for (const [id, address, name] of [[1, 0x210040, [0xbc, 0xd7]], [1112, 0x212040, [0xd2, 0xd2]]]) {
    word(0x200000 + id * 4, (address ^ 0x13131313) >>> 0);
    write(address & ~511, [0, 0, 0, 0, 3]);
    write(address + 8, [...name, 0].map(byte => byte ^ 0x5a));
}
vm.runInNewContext(fs.readFileSync(require.resolve('../src/agent.js'), 'utf8'), {
    PROFILE: {...profile, executable:'C:\\Game\\jshyl5.exe'},
    Process: {arch:'ia32', getModuleByName:() => ({base:new Pointer(base), path:'C:\\Game\\jshyl5.exe'})},
    ptr: value => new Pointer(value),
    Interceptor: {attach:(address, callbacks) => hooks.set(address.value - base, callbacks)},
    send: event => events.push(JSON.parse(JSON.stringify(event))),
    Uint8Array,
});
const assignment = hooks.get(0x2a9b70);
assert.ok(assignment, 'Capture must run at the assignment function, independently of drawing');
function commit(role, body) {
    word(owner + 0x158, role);
    const invocation={threadId:1, returnAddress:new Pointer(base+0xaaf34), context:{ecx:new Pointer(owner+0xfc)}};
    assignment.onEnter.call(invocation);
    write(text, body);
    word(owner + 0x100, body.length);
    assignment.onLeave.call(invocation);
}
const unrelated={returnAddress:new Pointer(base+0x123), context:{ecx:new Pointer(0)}};
assignment.onEnter.call(unrelated);
assignment.onLeave.call(unrelated);
assert.equal(recordsBeforeFirstCommit(), 0, 'Unrelated string assignments must be ignored');
function recordsBeforeFirstCommit() { return events.filter(event=>event.event==='dialogue').length; }
commit(1, [65]);
commit(1112, [66]);
commit(-1, [67]);
commit(1112, [66]);
commit(1112, [66]);
const records = () => events.filter(event => event.event === 'dialogue');
assert.deepEqual(records().map(({speaker, text}) => [speaker, text]), [
    [[0xbc,0xd7], [65]], [[0xd2,0xd2], [66]], [[], [67]],
    [[0xd2,0xd2], [66]], [[0xd2,0xd2], [66]],
], 'Each commit owns its speaker and body; identical later lines remain distinct');
for (let i = 0; i < 1000; i++) commit(i % 2 ? 1112 : 1, [i % 256]);
const stress = records().slice(5);
assert.equal(stress.length, 1000);
stress.forEach((record, i) => {
    assert.deepEqual(record.speaker, i % 2 ? [0xd2,0xd2] : [0xbc,0xd7]);
    assert.deepEqual(record.text, [i % 256]);
    assert.equal(record.sequence, i + 6);
});
console.log('Native committed snapshot checks passed (1,000 rapid speaker transitions).');
