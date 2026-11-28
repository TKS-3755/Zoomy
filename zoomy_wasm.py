"""Zoomy 7: the WebAssembly backend.

Compiles the statement tree of the native subset (numbers, flags, arrays, functions, routines, loops, printing, reading) to a
WebAssembly module that follows WASI (snapshot_preview1), so one .wasm file runs on Linux, macOS, Windows, in a browser, in
Node.js, wasmtime, wasmer, ... with no libc, no JavaScript glue and no other files.

This file has three parts:
  1. a small WebAssembly assembler (Module, Func) that writes the binary format directly,
  2. the runtime (number printing and reading, pow, integer division, errors ...), written with that assembler, and
  3. WasmCompiler, which walks the program tree the same way zoomy.AstCompiler does and produces the module.
Everything a program prints, and every runtime error message, is the same as in the native backend (tests/test_wasm.py checks that).
"""
import math
import struct

I32, I64, F64 = 0x7f, 0x7e, 0x7c
MASK64 = (1 << 64) - 1


class WasmError(Exception):
    pass


def uleb(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def sleb(n):
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        if (n == 0 and not b & 0x40) or (n == -1 and b & 0x40):
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


def vec(items):
    return uleb(len(items)) + b"".join(items)


def name_bytes(s):
    b = s.encode()
    return uleb(len(b)) + b


OPS = {
    "unreachable": 0x00, "nop": 0x01, "return": 0x0f, "drop": 0x1a, "select": 0x1b,
    "i32.eqz": 0x45, "i32.eq": 0x46, "i32.ne": 0x47, "i32.lt_s": 0x48, "i32.lt_u": 0x49, "i32.gt_s": 0x4a, "i32.gt_u": 0x4b,
    "i32.le_s": 0x4c, "i32.le_u": 0x4d, "i32.ge_s": 0x4e, "i32.ge_u": 0x4f,
    "i64.eqz": 0x50, "i64.eq": 0x51, "i64.ne": 0x52, "i64.lt_s": 0x53, "i64.lt_u": 0x54, "i64.gt_s": 0x55, "i64.gt_u": 0x56,
    "i64.le_s": 0x57, "i64.le_u": 0x58, "i64.ge_s": 0x59, "i64.ge_u": 0x5a,
    "f64.eq": 0x61, "f64.ne": 0x62, "f64.lt": 0x63, "f64.gt": 0x64, "f64.le": 0x65, "f64.ge": 0x66,
    "i32.clz": 0x67, "i32.ctz": 0x68, "i32.popcnt": 0x69, "i32.add": 0x6a, "i32.sub": 0x6b, "i32.mul": 0x6c,
    "i32.div_s": 0x6d, "i32.div_u": 0x6e, "i32.rem_s": 0x6f, "i32.rem_u": 0x70, "i32.and": 0x71, "i32.or": 0x72,
    "i32.xor": 0x73, "i32.shl": 0x74, "i32.shr_s": 0x75, "i32.shr_u": 0x76, "i32.rotl": 0x77, "i32.rotr": 0x78,
    "i64.clz": 0x79, "i64.ctz": 0x7a, "i64.popcnt": 0x7b, "i64.add": 0x7c, "i64.sub": 0x7d, "i64.mul": 0x7e,
    "i64.div_s": 0x7f, "i64.div_u": 0x80, "i64.rem_s": 0x81, "i64.rem_u": 0x82, "i64.and": 0x83, "i64.or": 0x84,
    "i64.xor": 0x85, "i64.shl": 0x86, "i64.shr_s": 0x87, "i64.shr_u": 0x88, "i64.rotl": 0x89, "i64.rotr": 0x8a,
    "f64.abs": 0x99, "f64.neg": 0x9a, "f64.ceil": 0x9b, "f64.floor": 0x9c, "f64.trunc": 0x9d, "f64.nearest": 0x9e,
    "f64.sqrt": 0x9f, "f64.add": 0xa0, "f64.sub": 0xa1, "f64.mul": 0xa2, "f64.div": 0xa3,
    "i32.wrap_i64": 0xa7, "i64.extend_i32_s": 0xac, "i64.extend_i32_u": 0xad,
    "f64.convert_i32_s": 0xb7, "f64.convert_i32_u": 0xb8, "f64.convert_i64_s": 0xb9, "f64.convert_i64_u": 0xba, "i64.reinterpret_f64": 0xbd, "f64.reinterpret_i64": 0xbf,
}
SAT = {"i64.trunc_sat_f64_s": 6, "i64.trunc_sat_f64_u": 7}            # 0xfc prefix
MEMOPS = {"i32.load16_u": (0x2f, 1), "i32.load": (0x28, 2), "i64.load": (0x29, 3), "f64.load": (0x2b, 3), "i32.load8_u": (0x2d, 0),
          "i32.store": (0x36, 2), "i64.store": (0x37, 3), "f64.store": (0x39, 3), "i32.store8": (0x3a, 0)}
BLOCK_VOID = 0x40


class Func:
    """one function; instructions are appended with the helper methods (stack machine, postfix order)"""

    def __init__(self, mod, name, params, results, export=None):
        self.mod, self.name = mod, name
        self.params, self.results = list(params), list(results)
        self.locals = []
        self.code = bytearray()
        self.ctl = []                   # open blocks, innermost last: the label id given to block/loop/if
        self.index = None
        self.export = export
        self.names = {}

    # -- locals
    def local(self, ty):
        self.locals.append(ty)
        return len(self.params) + len(self.locals) - 1

    def get(self, i):
        self.code += b"\x20" + uleb(i)

    def set(self, i):
        self.code += b"\x21" + uleb(i)

    def tee(self, i):
        self.code += b"\x22" + uleb(i)

    def gget(self, g):
        self.code += b"\x23" + uleb(g)

    def gset(self, g):
        self.code += b"\x24" + uleb(g)

    # -- constants
    def i32(self, n):
        n &= 0xffffffff
        self.code += b"\x41" + sleb(n - (1 << 32) if n >= 1 << 31 else n)

    def i64(self, n):
        n &= MASK64
        self.code += b"\x42" + sleb(n - (1 << 64) if n >= 1 << 63 else n)

    def f64(self, x):
        self.code += b"\x44" + struct.pack("<d", x)

    # -- plain instructions
    def op(self, *names):
        for n in names:
            if n in OPS:
                self.code.append(OPS[n])
            elif n in SAT:
                self.code += b"\xfc" + uleb(SAT[n])
            else:
                raise WasmError(f"unknown instruction {n}")

    def mem(self, name, offset=0):
        code, align = MEMOPS[name]
        self.code.append(code)
        self.code += uleb(align) + uleb(offset)

    def call(self, fn):
        self.code += b"\x10" + uleb(fn.index if isinstance(fn, (Func, Import)) else fn)

    # -- control flow. Each opener takes a label id (any hashable) so a branch can name its target.
    def _open(self, opcode, ty, label):
        self.code.append(opcode)
        self.code.append(BLOCK_VOID if ty is None else ty)
        self.ctl.append(label)

    def block(self, label=None, ty=None):
        self._open(0x02, ty, label)

    def loop(self, label=None, ty=None):
        self._open(0x03, ty, label)

    def if_(self, ty=None, label=None):
        self._open(0x04, ty, label)

    def else_(self):
        self.code.append(0x05)

    def end(self):
        self.code.append(0x0b)
        self.ctl.pop()

    def depth(self, label):
        for d, l in enumerate(reversed(self.ctl)):
            if l == label:
                return d
        raise WasmError(f"branch to a label that is not open: {label}")

    def br(self, label):
        self.code += b"\x0c" + uleb(self.depth(label))

    def br_if(self, label):
        self.code += b"\x0d" + uleb(self.depth(label))

    def ret(self):
        self.code.append(0x0f)

    # -- a compact text form:  "get:x i64:5 i64.add set:x if ... else ... end"
    def var(self, name, ty):
        idx = self.local(ty)
        self.names[name] = idx
        return idx

    def pn(self, *names):
        for i, n in enumerate(names):
            self.names[n] = i

    def _loc(self, t):
        return self.names[t] if t in self.names else int(t)

    def s(self, text):
        for line in text.split("\n"):
            for tok in line.split("#")[0].split():
                self._tok(tok)

    def _tok(self, tok):
        head, _, arg = tok.partition(":")
        mod = self.mod
        if head == "get":
            self.get(self._loc(arg))
        elif head == "set":
            self.set(self._loc(arg))
        elif head == "tee":
            self.tee(self._loc(arg))
        elif head == "gget":
            self.gget(mod.gnames[arg])
        elif head == "gset":
            self.gset(mod.gnames[arg])
        elif head == "i32":
            self.i32(int(arg, 0))
        elif head == "i64":
            self.i64(int(arg, 0))
        elif head == "f64":
            self.f64(float(arg))
        elif head == "call":
            self.call(mod.fnames[arg])
        elif head.split("/")[0] in ("block", "loop", "if"):
            kind, _, ty = head.partition("/")
            ty = {"": None, "i32": I32, "i64": I64, "f64": F64}[ty]
            getattr(self, {"block": "block", "loop": "loop", "if": "if_"}[kind])(arg or None, ty) if kind != "if" else self.if_(ty, arg or None)
        elif head == "else":
            self.else_()
        elif head == "end":
            self.end()
        elif head == "br":
            self.br(arg)
        elif head == "br_if":
            self.br_if(arg)
        elif head == "ret":
            self.ret()
        elif head in MEMOPS:
            self.mem(head, int(arg, 0) if arg else 0)
        else:
            self.op(head)

    def body_bytes(self):
        groups = []
        for t in self.locals:
            if groups and groups[-1][1] == t:
                groups[-1][0] += 1
            else:
                groups.append([1, t])
        body = vec([uleb(n) + bytes([t]) for n, t in groups]) + bytes(self.code) + b"\x0b"
        return uleb(len(body)) + body


class Import:
    def __init__(self, module, name, params, results, index):
        self.module, self.name, self.params, self.results, self.index = module, name, params, results, index


class Module:
    def __init__(self):
        self.imports, self.funcs, self.globals = [], [], []
        self.data = []                 # (offset, bytes)
        self.types = []
        self.pages = 1
        self.mem_export = True
        self.gnames, self.fnames = {}, {}

    def import_func(self, module, name, params, results):
        if self.funcs:
            raise WasmError("imports must be declared before functions")
        imp = Import(module, name, params, results, len(self.imports))
        self.imports.append(imp)
        self.fnames[name] = imp
        return imp

    def func(self, name, params=(), results=(), export=None):
        f = Func(self, name, params, results, export)
        f.index = len(self.imports) + len(self.funcs)
        self.funcs.append(f)
        self.fnames[name] = f
        return f

    def glob(self, ty, init=0, mutable=True, name=None):
        self.globals.append((ty, init, mutable))
        if name:
            self.gnames[name] = len(self.globals) - 1
        return len(self.globals) - 1

    def type_index(self, params, results):
        key = (tuple(params), tuple(results))
        if key not in self.types:
            self.types.append(key)
        return self.types.index(key)

    def encode(self):
        for imp in self.imports:
            self.type_index(imp.params, imp.results)
        for f in self.funcs:
            self.type_index(f.params, f.results)

        def section(sid, payload):
            return bytes([sid]) + uleb(len(payload)) + payload

        out = b"\x00asm\x01\x00\x00\x00"
        out += section(1, vec([b"\x60" + vec([bytes([t]) for t in p]) + vec([bytes([t]) for t in r]) for p, r in self.types]))
        out += section(2, vec([name_bytes(i.module) + name_bytes(i.name) + b"\x00" + uleb(self.type_index(i.params, i.results))
                               for i in self.imports]))
        out += section(3, vec([uleb(self.type_index(f.params, f.results)) for f in self.funcs]))
        out += section(5, vec([b"\x00" + uleb(self.pages)]))
        gl = []
        for ty, init, mutable in self.globals:
            if ty == I32:
                e = b"\x41" + sleb(init)
            elif ty == I64:
                e = b"\x42" + sleb(init)
            else:
                e = b"\x44" + struct.pack("<d", init)
            gl.append(bytes([ty, 1 if mutable else 0]) + e + b"\x0b")
        out += section(6, vec(gl))
        exports = [name_bytes("memory") + b"\x02\x00"] if self.mem_export else []
        for f in self.funcs:
            if f.export:
                exports.append(name_bytes(f.export) + b"\x00" + uleb(f.index))
        out += section(7, vec(exports))
        out += section(10, vec([f.body_bytes() for f in self.funcs]))
        out += section(11, vec([b"\x00\x41" + sleb(off) + b"\x0b" + uleb(len(d)) + d for off, d in self.data]))
        return out


# =============================================================================
# 2. The runtime
# =============================================================================
IOV, NWR, RET64 = 16, 24, 32          # scratch words: an iovec (ptr, len), a 32-bit result, a 64-bit result
SCR = 64                              # 64 bytes of digit scratch, 64..127
PATH = 256                            # 256 bytes for a file name
OUT_BUF, OUT_SIZE = 1024, 4096
IN_BUF, IN_SIZE = 5120, 4096
DATA_START = 9216
WASI = "wasi_snapshot_preview1"
LN2_HI, LN2_LO = 6.93147180369123816490e-01, 1.90821492927058770002e-10
INT_MIN = -(1 << 63)
INF = float('inf')
NAN = float('nan')

ERR_TEXT = {
    "index": "array index out of range",
    "step": "a 'for' loop needs a step that is not zero",
    "long": "this 'for' loop would run too long",
    "count": "a count cannot be negative",
    "deep": "too many nested calls (a function calls itself without stopping?)",
    "div0": "division by zero",
    "bit": "a shift or bit number must be from 0 to 63",
}


class Runtime:
    """the helper functions every program may call; they are added to the module in a fixed order"""

    def __init__(self, mod, string):
        self.mod = mod
        m = mod
        self.fd_write = m.import_func(WASI, "fd_write", [I32, I32, I32, I32], [I32])
        self.fd_read = m.import_func(WASI, "fd_read", [I32, I32, I32, I32], [I32])
        self.proc_exit = m.import_func(WASI, "proc_exit", [I32], [])
        self.clock_time_get = m.import_func(WASI, "clock_time_get", [I32, I64, I32], [I32])
        self.path_open = m.import_func(WASI, "path_open", [I32, I32, I32, I32, I32, I64, I64, I32, I32], [I32])
        self.fd_seek = m.import_func(WASI, "fd_seek", [I32, I64, I32, I32], [I32])
        self.fd_close = m.import_func(WASI, "fd_close", [I32], [I32])
        self.g_outlen = m.glob(I32, 0, name="outlen")
        self.g_inpos = m.glob(I32, 0, name="inpos")
        self.g_inend = m.glob(I32, 0, name="inend")
        self.g_pb = m.glob(I32, -1, name="pb")
        self.g_fd = m.glob(I32, 0, name="fd")
        self.g_depth = m.glob(I32, 0, name="depth")
        self.g_rvf = m.glob(F64, 0.0, name="rvf")
        self.g_rvi = m.glob(I64, 0, name="rvi")
        self.string = string
        self.make()

    # -- small helpers for writing the runtime
    def fn(self, name, params=(), results=()):
        return self.mod.func(name, params, results)

    def put_char(self, f, ch):
        f.i32(ord(ch))
        f.call(self.put)

    def make(self):
        m = self.mod
        # forward declarations so the functions can call each other in any order
        self.flush = self.fn("flush")
        self.put = self.fn("put", [I32])
        self.wbytes = self.fn("wbytes", [I32, I32])
        self.die = self.fn("die", [I32, I32, I32])
        self.errs = {k: self.fn("err_" + k) for k in ERR_TEXT}
        self.cvtt = self.fn("cvtt", [F64], [I64])
        self.chk_f = self.fn("chk_f", [F64, I32], [I32])
        self.chk_i = self.fn("chk_i", [I64, I32], [I32])
        self.put_u = self.fn("put_u", [I64])
        self.put_frac = self.fn("put_frac", [I64])
        self.print_i64 = self.fn("print_i64", [I64])
        self.print_u64 = self.fn("print_u64", [I64])
        self.print_f64 = self.fn("print_f64", [F64])
        self.ln = self.fn("ln", [F64], [F64])
        self.exp = self.fn("exp", [F64], [F64])
        self.pow_f = self.fn("pow_f", [F64, F64], [F64])
        self.pow_i = self.fn("pow_i", [I64, I64], [I64])
        self.isqrt = self.fn("isqrt", [I64], [I64])
        self.isqrt_u = self.fn("isqrt_u", [I64], [I64])
        self.sdiv = self.fn("sdiv", [I64, I64], [I64])
        self.smod = self.fn("smod", [I64, I64], [I64])
        self.srem = self.fn("srem", [I64, I64], [I64])
        self.udiv = self.fn("udiv", [I64, I64], [I64])
        self.urem = self.fn("urem", [I64, I64], [I64])
        self.bswap = self.fn("bswap", [I64], [I64])
        self.pext = self.fn("pext", [I64, I64], [I64])
        self.pdep = self.fn("pdep", [I64, I64], [I64])
        self.getc = self.fn("getc", [], [I32])
        self.read_f = self.fn("read_f", [], [I32])
        self.read_i = self.fn("read_i", [], [I32])
        self.read_c = self.fn("read_c", [], [I32])
        self.read_b = self.fn("read_b", [], [I32])
        self.clock_ms = self.fn("clock_ms", [], [I64])
        self.fopen = self.fn("fopen", [I32, I32], [I32])
        self.copy_path = self.fn("copy_path", [I32], [I32])
        self.fclose = self.fn("fclose")
        self.fseek = self.fn("fseek", [I64])
        self.fsize = self.fn("fsize", [], [I64])
        self.exit_code = self.fn("exit_code", [I64])
        self.body_io()
        self.body_errors()
        self.body_print()
        self.body_math()
        self.body_read()
        self.body_files()

    # ------------------------------------------------------------------ output and errors
    def body_io(self):
        f = self.flush
        f.gget(self.g_outlen)
        f.op("i32.eqz")
        f.if_()
        f.ret()
        f.end()
        f.i32(IOV)
        f.i32(OUT_BUF)
        f.mem("i32.store")
        f.i32(IOV)
        f.gget(self.g_outlen)
        f.mem("i32.store", 4)
        f.i32(1)
        f.i32(IOV)
        f.i32(1)
        f.i32(NWR)
        f.call(self.fd_write)
        f.op("drop")
        f.i32(0)
        f.gset(self.g_outlen)

        f = self.put                              # put(byte)
        f.gget(self.g_outlen)
        f.get(0)
        f.mem("i32.store8", OUT_BUF)
        f.gget(self.g_outlen)
        f.i32(1)
        f.op("i32.add")
        f.gset(self.g_outlen)
        f.gget(self.g_outlen)
        f.i32(OUT_SIZE)
        f.op("i32.ge_u")
        f.if_()
        f.call(self.flush)
        f.end()

        f = self.wbytes                           # wbytes(ptr, len)
        f.block("brk")
        f.loop("top")
        f.get(1)
        f.op("i32.eqz")
        f.br_if("brk")
        f.get(0)
        f.mem("i32.load8_u")
        f.call(self.put)
        f.get(0)
        f.i32(1)
        f.op("i32.add")
        f.set(0)
        f.get(1)
        f.i32(1)
        f.op("i32.sub")
        f.set(1)
        f.br("top")
        f.end()
        f.end()

        f = self.die                              # die(ptr, len): flush stdout, write the message to stderr, exit(255)
        f.call(self.flush)
        f.i32(IOV)
        f.get(0)
        f.mem("i32.store")
        f.i32(IOV)
        f.get(1)
        f.mem("i32.store", 4)
        f.i32(2)
        f.i32(IOV)
        f.i32(1)
        f.i32(NWR)
        f.call(self.fd_write)
        f.op("drop")
        f.get(2)
        f.call(self.proc_exit)
        f.op("unreachable")

        f = self.exit_code                        # exit_code(i64): flush, leave with the low 8 bits
        f.call(self.flush)
        f.get(0)
        f.i64(255)
        f.op("i64.and", "i32.wrap_i64")
        f.call(self.proc_exit)

    def body_errors(self):
        for k, text in ERR_TEXT.items():
            msg = ("zoomy: runtime error: " + text + "\n").encode()
            off = self.string(msg)
            f = self.errs[k]
            f.i32(off)
            f.i32(len(msg))
            f.i32(255)
            f.call(self.die)
        # cvtt(x): like the x86 cvttsd2si, the "integer indefinite" value for NaN and out-of-range numbers
        f = self.cvtt
        f.get(0)
        f.get(0)
        f.op("f64.ne")
        f.get(0)
        f.op("f64.abs")
        f.f64(9223372036854775808.0)
        f.op("f64.ge", "i32.or")
        f.if_(I64)
        f.i64(INT_MIN)
        f.else_()
        f.get(0)
        f.op("i64.trunc_sat_f64_s")
        f.end()
        f = self.chk_f                            # chk_f(x, size) -> index, or the index error
        t = f.local(I64)
        f.get(0)
        f.call(self.cvtt)
        f.set(t)
        f.get(t)
        f.get(1)
        f.op("i64.extend_i32_u", "i64.ge_u")
        f.if_()
        f.call(self.errs["index"])
        f.end()
        f.get(t)
        f.op("i32.wrap_i64")
        f = self.chk_i
        f.get(0)
        f.get(1)
        f.op("i64.extend_i32_u", "i64.ge_u")
        f.if_()
        f.call(self.errs["index"])
        f.end()
        f.get(0)
        f.op("i32.wrap_i64")

    # ------------------------------------------------------------------ printing numbers
    def body_print(self):
        f = self.put_u                            # put_u(v): the unsigned decimal of v
        p = f.local(I32)
        f.get(0)
        f.op("i64.eqz")
        f.if_()
        self.put_char(f, "0")
        f.ret()
        f.end()
        f.i32(SCR + 64)
        f.set(p)
        f.block("brk")
        f.loop("top")
        f.get(0)
        f.op("i64.eqz")
        f.br_if("brk")
        f.get(p)
        f.i32(1)
        f.op("i32.sub")
        f.set(p)
        f.get(p)
        f.get(0)
        f.i64(10)
        f.op("i64.rem_u", "i32.wrap_i64")
        f.i32(48)
        f.op("i32.add")
        f.mem("i32.store8")
        f.get(0)
        f.i64(10)
        f.op("i64.div_u")
        f.set(0)
        f.br("top")
        f.end()
        f.end()
        f.block("brk2")
        f.loop("top2")
        f.get(p)
        f.i32(SCR + 64)
        f.op("i32.ge_u")
        f.br_if("brk2")
        f.get(p)
        f.mem("i32.load8_u")
        f.call(self.put)
        f.get(p)
        f.i32(1)
        f.op("i32.add")
        f.set(p)
        f.br("top2")
        f.end()
        f.end()

        f = self.put_frac                         # put_frac(fd): '.' and the six decimals of fd (1..999999) without trailing zeros
        nd = f.local(I32)
        i = f.local(I32)
        self.put_char(f, ".")
        f.i32(6)
        f.set(nd)
        f.block("brk")
        f.loop("top")
        f.get(0)
        f.i64(10)
        f.op("i64.rem_u", "i64.eqz", "i32.eqz")
        f.br_if("brk")
        f.get(0)
        f.i64(10)
        f.op("i64.div_u")
        f.set(0)
        f.get(nd)
        f.i32(1)
        f.op("i32.sub")
        f.set(nd)
        f.br("top")
        f.end()
        f.end()
        f.get(nd)
        f.set(i)
        f.block("brk2")
        f.loop("top2")
        f.get(i)
        f.op("i32.eqz")
        f.br_if("brk2")
        f.get(i)
        f.i32(1)
        f.op("i32.sub")
        f.set(i)
        f.i32(SCR)
        f.get(i)
        f.op("i32.add")
        f.get(0)
        f.i64(10)
        f.op("i64.rem_u", "i32.wrap_i64")
        f.i32(48)
        f.op("i32.add")
        f.mem("i32.store8")
        f.get(0)
        f.i64(10)
        f.op("i64.div_u")
        f.set(0)
        f.br("top2")
        f.end()
        f.end()
        f.i32(0)
        f.set(i)
        f.block("brk3")
        f.loop("top3")
        f.get(i)
        f.get(nd)
        f.op("i32.ge_u")
        f.br_if("brk3")
        f.i32(SCR)
        f.get(i)
        f.op("i32.add")
        f.mem("i32.load8_u")
        f.call(self.put)
        f.get(i)
        f.i32(1)
        f.op("i32.add")
        f.set(i)
        f.br("top3")
        f.end()
        f.end()

        f = self.print_u64
        f.get(0)
        f.call(self.put_u)
        f = self.print_i64
        f.get(0)
        f.i64(0)
        f.op("i64.lt_s")
        f.if_()
        self.put_char(f, "-")
        f.i64(0)
        f.get(0)
        f.op("i64.sub")
        f.set(0)
        f.end()
        f.get(0)
        f.call(self.put_u)

        # print_f64(x): nan | inf | -inf | 0, else 1e-6 <= |x| < 1e15 in plain notation with up to 6 decimals, else d[.dddddd]e+XX
        f = self.print_f64
        absb, ip, fd, e = f.local(I64), f.local(I64), f.local(I64), f.local(I64)
        ax, mm = f.local(F64), f.local(F64)
        neg = f.local(I32)
        f.get(0)
        f.get(0)
        f.op("f64.ne")
        f.if_()
        for ch in "nan":
            self.put_char(f, ch)
        f.ret()
        f.end()
        f.get(0)
        f.op("i64.reinterpret_f64")
        f.i64(63)
        f.op("i64.shr_u", "i32.wrap_i64")
        f.set(neg)
        f.get(0)
        f.op("i64.reinterpret_f64")
        f.i64(0x7FFFFFFFFFFFFFFF)
        f.op("i64.and")
        f.set(absb)
        f.get(absb)
        f.i64(0x7FF0000000000000)
        f.op("i64.eq")
        f.if_()
        f.get(neg)
        f.if_()
        self.put_char(f, "-")
        f.end()
        for ch in "inf":
            self.put_char(f, ch)
        f.ret()
        f.end()
        f.get(absb)
        f.op("i64.eqz")
        f.if_()
        self.put_char(f, "0")
        f.ret()
        f.end()
        f.get(absb)
        f.op("f64.reinterpret_i64")
        f.set(ax)
        f.get(neg)
        f.if_()
        self.put_char(f, "-")
        f.end()

        def digits(m_local):                     # ip = whole part, fd = round-half-even(fraction * 1e6), carried
            f.get(m_local)
            f.op("i64.trunc_sat_f64_s")
            f.set(ip)
            f.get(m_local)
            f.get(ip)
            f.op("f64.convert_i64_s", "f64.sub")
            f.f64(1e6)
            f.op("f64.mul", "f64.nearest", "i64.trunc_sat_f64_s")
            f.set(fd)
            f.get(fd)
            f.i64(1000000)
            f.op("i64.ge_s")
            f.if_()
            f.get(ip)
            f.i64(1)
            f.op("i64.add")
            f.set(ip)
            f.get(fd)
            f.i64(1000000)
            f.op("i64.sub")
            f.set(fd)
            f.end()

        f.get(absb)
        f.i64(0x430C6BF526340000)                 # 1e15
        f.op("i64.ge_u")
        f.get(absb)
        f.i64(0x3EB0C6F7A0B5ED8D)                 # 1e-6
        f.op("i64.lt_u", "i32.or")
        f.if_()
        # ---- scientific
        f.i64(0)
        f.set(e)
        f.get(ax)
        f.set(mm)
        f.block("b1")
        f.loop("l1")
        f.get(mm)
        f.f64(10.0)
        f.op("f64.lt")
        f.br_if("b1")
        f.get(mm)
        f.f64(10.0)
        f.op("f64.div")
        f.set(mm)
        f.get(e)
        f.i64(1)
        f.op("i64.add")
        f.set(e)
        f.br("l1")
        f.end()
        f.end()
        f.block("b2")
        f.loop("l2")
        f.get(mm)
        f.f64(1.0)
        f.op("f64.ge")
        f.br_if("b2")
        f.get(mm)
        f.f64(10.0)
        f.op("f64.mul")
        f.set(mm)
        f.get(e)
        f.i64(1)
        f.op("i64.sub")
        f.set(e)
        f.br("l2")
        f.end()
        f.end()
        digits(mm)
        f.get(ip)
        f.i64(10)
        f.op("i64.ge_u")
        f.if_()
        f.i64(1)
        f.set(ip)
        f.get(e)
        f.i64(1)
        f.op("i64.add")
        f.set(e)
        f.end()
        f.get(ip)
        f.call(self.put_u)
        f.get(fd)
        f.op("i64.eqz", "i32.eqz")
        f.if_()
        f.get(fd)
        f.call(self.put_frac)
        f.end()
        self.put_char(f, "e")
        f.get(e)
        f.i64(0)
        f.op("i64.lt_s")
        f.if_()
        self.put_char(f, "-")
        f.i64(0)
        f.get(e)
        f.op("i64.sub")
        f.set(e)
        f.else_()
        self.put_char(f, "+")
        f.end()
        f.get(e)
        f.i64(10)
        f.op("i64.lt_u")
        f.if_()
        self.put_char(f, "0")
        f.end()
        f.get(e)
        f.call(self.put_u)
        f.else_()
        # ---- plain
        digits(ax)
        f.get(ip)
        f.call(self.put_u)
        f.get(fd)
        f.op("i64.eqz", "i32.eqz")
        f.if_()
        f.get(fd)
        f.call(self.put_frac)
        f.end()
        f.end()

    # ------------------------------------------------------------------ integer helpers, pow, roots, bit tricks
    def body_math(self):
        f = self.sdiv
        f.pn("a", "b")
        f.s("""get:b i64.eqz if call:err_div0 end
               get:b i64:-1 i64.eq if i64:0 get:a i64.sub ret end
               get:a get:b i64.div_s""")
        f = self.smod
        f.pn("a", "b")
        f.var("r", I64)
        f.s("""get:b i64.eqz if call:err_div0 end
               get:b i64:-1 i64.eq if i64:0 ret end
               get:a get:b i64.rem_s set:r
               get:r i64.eqz i32.eqz  get:r get:b i64.xor i64:0 i64.lt_s  i32.and
               if get:r get:b i64.add set:r end
               get:r""")
        f = self.srem
        f.pn("a", "b")
        f.s("""get:b i64.eqz if call:err_div0 end
               get:b i64:-1 i64.eq if i64:0 ret end
               get:a get:b i64.rem_s""")
        f = self.udiv
        f.pn("a", "b")
        f.s("get:b i64.eqz if call:err_div0 end  get:a get:b i64.div_u")
        f = self.urem
        f.pn("a", "b")
        f.s("get:b i64.eqz if call:err_div0 end  get:a get:b i64.rem_u")

        f = self.isqrt_u                          # floor(sqrt(n)) for an unsigned n, digit by digit
        f.pn("n")
        f.var("r", I64)
        f.var("c", I64)
        f.var("t", I64)
        f.s("""i64:0 set:r  i64:0x4000000000000000 set:c
               block:b1 loop:l1
                 get:c get:n i64.le_u br_if:b1
                 get:c i64:2 i64.shr_u tee:c i64.eqz if i64:0 ret end
                 br:l1
               end end
               block:b2 loop:l2
                 get:r get:c i64.add set:t
                 get:n get:t i64.ge_u
                 if
                   get:n get:t i64.sub set:n
                   get:r i64:1 i64.shr_u get:c i64.add set:r
                 else
                   get:r i64:1 i64.shr_u set:r
                 end
                 get:c i64:2 i64.shr_u tee:c i64.eqz br_if:b2
                 br:l2
               end end
               get:r""")
        f = self.isqrt
        f.pn("n")
        f.s("get:n i64:0 i64.le_s if i64:0 ret end  get:n call:isqrt_u")

        f = self.bswap
        f.pn("v")
        f.var("r", I64)
        f.var("k", I32)
        f.s("""i64:0 set:r  i32:8 set:k
               block:b loop:l
                 get:k i32.eqz br_if:b
                 get:r i64:8 i64.shl  get:v i64:255 i64.and  i64.or set:r
                 get:v i64:8 i64.shr_u set:v
                 get:k i32:1 i32.sub set:k
                 br:l
               end end
               get:r""")
        f = self.pext
        f.pn("v", "m")
        f.var("r", I64)
        f.var("k", I64)
        f.var("low", I64)
        f.s("""block:b loop:l
                 get:m i64.eqz br_if:b
                 get:m i64:0 get:m i64.sub i64.and set:low
                 get:v get:low i64.and i64.eqz i32.eqz
                 if get:r i64:1 get:k i64.shl i64.or set:r end
                 get:k i64:1 i64.add set:k
                 get:m get:m i64:1 i64.sub i64.and set:m
                 br:l
               end end
               get:r""")
        f = self.pdep
        f.pn("v", "m")
        f.var("r", I64)
        f.var("k", I64)
        f.var("low", I64)
        f.s("""block:b loop:l
                 get:m i64.eqz br_if:b
                 get:m i64:0 get:m i64.sub i64.and set:low
                 get:v get:k i64.shr_u i64:1 i64.and i64.eqz i32.eqz
                 if get:r get:low i64.or set:r end
                 get:k i64:1 i64.add set:k
                 get:m get:m i64:1 i64.sub i64.and set:m
                 br:l
               end end
               get:r""")

        # ln(x) for a finite x > 0: x = m * 2^e with m in [0.7, 1.42], ln m = 2 atanh((m-1)/(m+1))
        f = self.ln
        f.pn("x")
        e, bits, m, sv, z, acc = f.var("e", F64), f.var("bits", I64), f.var("m", F64), f.var("s", F64), f.var("z", F64), f.var("acc", F64)
        f.s("""f64:0 set:e
               get:x f64:2.2250738585072014e-308 f64.lt
               if get:x f64:18014398509481984.0 f64.mul set:x  f64:-54 set:e end
               get:x i64.reinterpret_f64 set:bits
               get:e get:bits i64:52 i64.shr_u i64:2047 i64.and i64:1023 i64.sub f64.convert_i64_s f64.add set:e
               get:bits i64:0x000FFFFFFFFFFFFF i64.and i64:0x3FF0000000000000 i64.or f64.reinterpret_i64 set:m
               get:m f64:1.4142135623730951 f64.gt
               if get:m f64:0.5 f64.mul set:m  get:e f64:1 f64.add set:e end
               get:m f64:1 f64.sub get:m f64:1 f64.add f64.div set:s
               get:s get:s f64.mul set:z""")
        f.f64(1 / 27)
        f.set(acc)
        for d in range(25, 0, -2):
            f.s("get:acc get:z f64.mul")
            f.f64(1 / d)
            f.s("f64.add set:acc")
        f.f64(LN2_HI)
        f.s("set:m")                                # m is free now: reuse it for ln2_hi
        f.s("get:e get:m f64.mul")
        f.s("f64:2 get:s f64.mul get:acc f64.mul")
        f.f64(LN2_LO)
        f.s("get:e f64.mul f64.add f64.add")

        # exp(y)
        f = self.exp
        f.pn("y")
        k, r, acc, ki, h = f.var("k", F64), f.var("r", F64), f.var("acc", F64), f.var("ki", I64), f.var("h", I64)
        f.s("""get:y get:y f64.ne if get:y ret end
               get:y f64:709.782712893384 f64.gt if f64:inf ret end
               get:y f64:-745.2 f64.lt if f64:0 ret end
               get:y f64:1.4426950408889634 f64.mul f64.nearest set:k""")
        f.f64(LN2_HI)
        f.s("get:k f64.mul get:y f64.sub f64.neg")   # -(k*hi - y) = y - k*hi
        f.f64(LN2_LO)
        f.s("get:k f64.mul f64.sub set:r")
        f.s("f64:1 set:acc")
        for n in range(18, 0, -1):
            f.s("get:acc get:r")
            f.f64(float(n))
            f.s("f64.div f64.mul f64:1 f64.add set:acc")
        f.s("""get:k i64.trunc_sat_f64_s set:ki
               get:ki i64:1 i64.shr_s set:h
               get:acc
               get:h i64:1023 i64.add i64:52 i64.shl f64.reinterpret_i64 f64.mul
               get:ki get:h i64.sub i64:1023 i64.add i64:52 i64.shl f64.reinterpret_i64 f64.mul""")

        f = self.pow_f                            # x ^ e: whole exponents by squaring, others through exp(e ln x)
        f.pn("x", "e")
        ab, n, res = f.var("ab", I64), f.var("n", I64), f.var("res", F64)
        f.s("""block:nw
                 get:e get:e f64.ne br_if:nw
                 get:e i64.reinterpret_f64 i64:0x7FFFFFFFFFFFFFFF i64.and set:ab
                 get:ab i64:0x43E0000000000000 i64.ge_u br_if:nw
                 get:ab f64.reinterpret_i64 i64.trunc_sat_f64_s set:n
                 get:n f64.convert_i64_s get:ab f64.reinterpret_i64 f64.ne br_if:nw
                 f64:1 set:res
                 block:b loop:l
                   get:n i64.eqz br_if:b
                   get:n i64:1 i64.and i64.eqz i32.eqz
                   if get:res get:x f64.mul set:res end
                   get:x get:x f64.mul set:x
                   get:n i64:1 i64.shr_u set:n
                   br:l
                 end end
                 get:e i64.reinterpret_f64 i64:0 i64.lt_s
                 if f64:1 get:res f64.div ret end
                 get:res ret
               end
               get:e get:e f64.ne if f64:nan ret end
               get:x get:x f64.ne if get:x ret end
               get:x f64:0 f64.lt if f64:nan ret end
               get:x f64:0 f64.eq
               if
                 get:e f64:0 f64.gt if f64:0 ret end
                 f64:inf ret
               end
               get:x f64:inf f64.eq
               if
                 get:e f64:0 f64.gt if f64:inf ret end
                 f64:0 ret
               end
               get:e get:x call:ln f64.mul call:exp""")

        f = self.pow_i                            # integers: a negative exponent gives 0 (but 1 ^ n = 1, (-1) ^ n = +-1)
        f.pn("b", "e")
        r = f.var("r", I64)
        f.s("""get:e i64:0 i64.lt_s
               if
                 get:b i64:1 i64.eq if i64:1 ret end
                 get:b i64:-1 i64.eq if get:e i64:1 i64.and i64.eqz if i64:1 ret end i64:-1 ret end
                 get:b i64.eqz if call:err_div0 end
                 i64:0 ret
               end
               i64:1 set:r
               block:bk loop:l
                 get:e i64.eqz br_if:bk
                 get:e i64:1 i64.and i64.eqz i32.eqz
                 if get:r get:b i64.mul set:r end
                 get:b get:b i64.mul set:b
                 get:e i64:1 i64.shr_u set:e
                 br:l
               end end
               get:r""")

    # ------------------------------------------------------------------ input
    def body_read(self):
        f = self.getc
        c = f.var("c", I32)
        f.s("""gget:pb tee:c i32:-1 i32.ne
               if i32:-1 gset:pb get:c ret end
               gget:fd
               if
                 i32:16 i32:8 i32.store  i32:16 i32:1 i32.store:4
                 gget:fd i32:16 i32:1 i32:24 call:fd_read
                 if i32:-1 ret end
                 i32:24 i32.load i32.eqz if i32:-1 ret end
                 i32:8 i32.load8_u ret
               end
               gget:inpos gget:inend i32.lt_u
               if
                 gget:inpos i32.load8_u:%d
                 gget:inpos i32:1 i32.add gset:inpos
                 ret
               end
               call:flush
               i32:16 i32:%d i32.store  i32:16 i32:%d i32.store:4
               i32:0 i32:16 i32:1 i32:24 call:fd_read
               if i32:-1 ret end
               i32:24 i32.load tee:c i32.eqz if i32:-1 ret end
               get:c gset:inend  i32:1 gset:inpos
               i32:%d i32.load8_u""" % (IN_BUF, IN_BUF, IN_SIZE, IN_BUF))

        SKIP = """block:sk loop:sl
                    call:getc tee:c
                    i32:-1 i32.eq if %s end
                    get:c i32:32 i32.eq br_if:sl
                    get:c i32:9 i32.sub i32:4 i32.le_u br_if:sl
                  end end
                  get:c i32:45 i32.eq
                  if i32:1 set:neg call:getc set:c
                  else get:c i32:43 i32.eq if call:getc set:c end end"""

        f = self.read_f                           # [whitespace] [+|-] digits [. digits]; m = m*10 + digit, result m / 10^(digits after the dot)
        c, neg, nd, nf, dot = f.var("c", I32), f.var("neg", I32), f.var("nd", I32), f.var("nf", I32), f.var("dot", I32)
        m, p = f.var("m", F64), f.var("p", F64)
        f.s(SKIP % "f64:0 gset:rvf i32:0 ret")
        f.s("""f64:0 set:m
               block:bk loop:lp
                 get:c i32:-1 i32.eq br_if:bk
                 get:c i32:48 i32.sub i32:9 i32.le_u
                 if
                   get:m f64:10 f64.mul  get:c i32:48 i32.sub i64.extend_i32_u f64.convert_i64_s  f64.add set:m
                   get:nd i32:1 i32.add set:nd
                   get:dot if get:nf i32:1 i32.add set:nf end
                   call:getc set:c br:lp
                 end
                 get:c i32:46 i32.eq get:dot i32.eqz i32.and
                 if i32:1 set:dot call:getc set:c br:lp end
                 get:c gset:pb
               end end
               get:nd i32.eqz if i32:-1 gset:pb f64:0 gset:rvf i32:0 ret end
               f64:1 set:p
               block:b2 loop:l2
                 get:nf i32.eqz br_if:b2
                 get:p f64:10 f64.mul set:p
                 get:nf i32:1 i32.sub set:nf
                 br:l2
               end end
               get:m get:p f64.div set:m
               get:neg if get:m f64.neg set:m end
               get:m gset:rvf i32:1""")

        f = self.read_i
        c, neg, nd, m = f.var("c", I32), f.var("neg", I32), f.var("nd", I32), f.var("m", I64)
        f.s(SKIP % "i64:0 gset:rvi i32:0 ret")
        f.s("""i64:0 set:m
               block:bk loop:lp
                 get:c i32:-1 i32.eq br_if:bk
                 get:c i32:48 i32.sub i32:9 i32.le_u
                 if
                   get:m i64:10 i64.mul  get:c i32:48 i32.sub i64.extend_i32_u  i64.add set:m
                   get:nd i32:1 i32.add set:nd
                   call:getc set:c br:lp
                 end
                 get:c gset:pb
               end end
               get:nd i32.eqz if i32:-1 gset:pb i64:0 gset:rvi i32:0 ret end
               get:neg if i64:0 get:m i64.sub set:m end
               get:m gset:rvi i32:1""")

        f = self.read_c                           # the next character that is not white space
        c = f.var("c", I32)
        f.s("""block:sk loop:sl
                 call:getc tee:c
                 i32:-1 i32.eq if i64:0 gset:rvi i32:0 ret end
                 get:c i32:32 i32.eq br_if:sl
                 get:c i32:9 i32.sub i32:4 i32.le_u br_if:sl
               end end
               get:c i64.extend_i32_u gset:rvi i32:1""")
        f = self.read_b                           # the next byte, white space included
        c = f.var("c", I32)
        f.s("""call:getc tee:c i32:-1 i32.eq if i64:0 gset:rvi i32:0 ret end
               get:c i64.extend_i32_u gset:rvi i32:1""")

    # ------------------------------------------------------------------ files and the clock
    def body_files(self):
        f = self.fopen                            # fopen(ptr, len): ok flag; the file becomes the input
        f.pn("ptr", "len")
        f.s("""i32:3 i32:1 get:ptr get:len i32:0 i64:38 i64:0 i32:0 i32:32 call:path_open
               if i32:0 ret end
               i32:32 i32.load gset:fd
               i32:-1 gset:pb
               i32:1""")
        f = self.copy_path                        # copy_path(array): the characters (one per 8-byte slot, 0 at the end) into PATH
        f.pn("src")
        i, t = f.var("i", I32), f.var("t", I32)
        f.s("""block:b loop:l
                 get:i i32:255 i32.ge_u br_if:b
                 get:src get:i i32:3 i32.shl i32.add i64.load i32.wrap_i64 i32:255 i32.and set:t
                 i32:%d get:i i32.add get:t i32.store8
                 get:t i32.eqz if get:i ret end
                 get:i i32:1 i32.add set:i
                 br:l
               end end
               i32:%d get:i i32.add i32:0 i32.store8
               get:i""" % (PATH, PATH))
        f = self.fclose
        f.s("""gget:fd if gget:fd call:fd_close drop end
               i32:0 gset:fd  i32:-1 gset:pb""")
        f = self.fseek
        f.pn("off")
        f.s("""gget:fd get:off i32:0 i32:32 call:fd_seek drop
               i32:-1 gset:pb""")
        f = self.fsize
        f.s("""i32:32 i64:-1 i64.store
               gget:fd i64:0 i32:2 i32:32 call:fd_seek drop
               i32:-1 gset:pb
               i32:32 i64.load""")
        f = self.clock_ms
        f.s("""i32:1 i64:1 i32:32 call:clock_time_get drop
               i32:32 i64.load i64:1000000 i64.div_u""")


# =============================================================================
# 3. The compiler
# =============================================================================
ARR_START = 1 << 20                   # arrays live above 1 MiB; the strings of the program are below
ARR_LIMIT = 1 << 31                   # at most 2 GiB of arrays
MAX_DEPTH = 100000                    # calls a recursive function may nest (the native cap; the host stack must be big enough, see zoomy_wasm_host.js)

UNSUPPORTED = {
    "workers": "'start workers' (there are no threads in this backend)",
    "waitw": "'wait for the workers' (there are no threads in this backend)",
    "syscall": "'call the system with the phone number' (WebAssembly programs cannot call the operating system directly)",
    "runwith": "'extern' functions (they are native code)",
    "extern": "'extern' functions (they are native code)",
}


def _zerr(msg, file, line):
    from zoomy_py import ZoomyError
    return ZoomyError(msg, file, line)


class Ctx:
    """one function being compiled: its Func, its local variables and the stack of loops it is inside"""

    def __init__(self, func, is_main, local_names):
        self.f, self.is_main, self.local_names = func, is_main, local_names
        self.vars = {}                  # name -> local index
        self.free = {I32: [], I64: [], F64: []}
        self.loops = []                 # (break label, continue label)


def _strings_in(obj, out):
    if isinstance(obj, str):
        out.add(obj)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            _strings_in(x, out)


class WasmCompiler:
    CMPOP = {"eq": "eq", "ne": "ne", "lt": "lt", "gt": "gt", "ge": "ge", "le": "le"}

    def __init__(self, prog, max_depth=MAX_DEPTH):
        from zoomy_py import all_stmts, assigned_names
        self.prog, self.zall, self.zassigned = prog, all_stmts, assigned_names
        self.ints = getattr(prog, "ints", False)
        self.uns = self.ints and getattr(prog, "uns", False)
        self.T = I64 if self.ints else F64
        self.max_depth = max_depth
        self.mod = Module()
        self.strs, self.str_end = {}, DATA_START
        self.rt = Runtime(self.mod, self.string)
        self.gvars = {}
        self.arrays, self.arr_end = {}, ARR_START
        self.labels = 0
        self.fdefs, self.routines, self.funcs, self.pending = {}, {}, {}, []
        self.recursive = set()
        self.node_line = 0
        self.char_vars = {s[4][1] for s in self.zall(prog.stmts) if s[0] == "convert" and s[2] == "number"}
        self.assigned = set()
        for st in self.zall(prog.stmts):
            self.assigned.update(self.zassigned(st))
        self.flag_temps = set()
        self.ctx = None

    # ------------------------------------------------------------------ small helpers
    @property
    def f(self):
        return self.ctx.f

    def fail(self, msg):
        return _zerr(msg, self.prog.file, self.node_line)

    def string(self, data):
        if data in self.strs:
            return self.strs[data]
        off = self.str_end
        self.str_end += len(data)
        if self.str_end > ARR_START:
            raise self.fail("the program has too much text for the WebAssembly backend (more than 1 MB)")
        self.strs[data] = off
        self.mod.data.append((off, data))
        return off

    def label(self):
        self.labels += 1
        return self.labels

    def tmp(self, ty=None):
        ty = ty or self.T
        free = self.ctx.free[ty]
        return free.pop() if free else self.f.local(ty)

    def drop(self, idx, ty=None):
        self.ctx.free[ty or self.T].append(idx)

    def const(self, v):
        """push a number of the program's own kind"""
        if self.ints:
            self.f.i64(int(v))
        else:
            self.f.f64(float(v))

    def bool_to_value(self):
        self.f.op("i64.extend_i32_u" if self.ints else "f64.convert_i32_u")

    def to_i64(self):
        """the value on the stack as an integer: floats are truncated the way the x86 cvttsd2si does"""
        if not self.ints:
            self.f.call(self.rt.cvtt)

    def from_i64(self):
        if not self.ints:
            self.f.op("f64.convert_i64_s")

    # ------------------------------------------------------------------ variables
    def is_flag(self, e):
        return e[0] in ("bool", "cmp", "and", "or", "not") or (e[0] == "var" and (e[1] in self.prog.n_flags or e[1] in self.flag_temps)) \
            or (e[0] == "wl" and e[2])

    def vloc(self, name):
        c = self.ctx
        if name in c.vars:
            return "l", c.vars[name]
        if name != "input_ok" and name in c.local_names:
            c.vars[name] = c.f.local(self.T)
            return "l", c.vars[name]
        if name not in self.gvars:
            self.gvars[name] = self.mod.glob(self.T, 0 if self.ints else 0.0)
        return "g", self.gvars[name]

    def vget(self, name):
        if name == "pi" and "pi" not in self.assigned:
            self.const(3 if self.ints else 3.141592653589793)
            return
        if name in self.arrays:
            raise self.fail(f"'{name}' is an array; use 'load from' / 'store ... in' to access it")
        kind, i = self.vloc(name)
        (self.f.get if kind == "l" else self.f.gget)(i)

    def vset(self, name):
        if name in self.arrays:
            raise self.fail(f"'{name}' is an array; use 'load from' / 'store ... in' to access it")
        kind, i = self.vloc(name)
        (self.f.set if kind == "l" else self.f.gset)(i)

    def set_ok(self, ok):
        self.const(1 if ok else 0)
        self.vset("input_ok")

    # ------------------------------------------------------------------ arrays
    def allocate(self, name, size, shared):
        if shared:
            raise self.fail("shared arrays need threads, which the WebAssembly backend does not have")
        if size < 1:
            raise self.fail("an array needs at least 1 slot")
        if name in self.arrays:
            if self.arrays[name][1] != size:
                raise self.fail(f"array '{name}' was already allocated with {self.arrays[name][1]} slots")
            return
        if self.arr_end - ARR_START + 8 * size > ARR_LIMIT:
            raise self.fail("the arrays need more than 2 GB")
        self.arrays[name] = (self.arr_end, size)
        self.arr_end += 8 * size

    def array(self, name):
        if name not in self.arrays:
            raise self.fail(f"array '{name}' is used before 'allocate array {name} with N slots'")
        return self.arrays[name]

    def index(self, key, size):
        """push the checked byte offset (an i32) of slot KEY; a constant key is checked right now"""
        f = self.f
        if key[0] == "num" and not self.ints:
            k = int(float(key[1])) if key[1] == key[1] else None
        elif key[0] == "num":
            k = int(key[1]) & MASK64
        else:
            k = None
        if k is not None:
            if 0 <= k < size:
                f.i32(8 * k)
            else:
                f.call(self.rt.errs["index"])
                f.i32(0)
            return
        self.ex(key)
        f.i32(size)
        f.call(self.rt.chk_i if self.ints else self.rt.chk_f)
        f.i32(3)
        f.op("i32.shl")

    def load_op(self):
        return "i64.load" if self.ints else "f64.load"

    def store_op(self):
        return "i64.store" if self.ints else "f64.store"

    # ------------------------------------------------------------------ expressions
    def ex(self, e):
        f, k, T = self.f, e[0], self.T
        if k == "num":
            self.const(int(e[1]) & MASK64 if self.ints else e[1])
        elif k == "var":
            self.vget(e[1])
        elif k == "wl":
            f.get(e[1])
        elif k == "neg":
            if self.ints:
                f.i64(0)
                self.ex(e[1])
                f.op("i64.sub")
            else:
                self.ex(e[1])
                f.op("f64.neg")
        elif k == "bin":
            self.binary(e)
        elif k == "bitop":
            self.bitop(e)
        elif k == "bool":
            self.const(1 if e[1] else 0)
        elif k in ("cmp", "and", "or", "not"):
            self.cond(e)
            self.bool_to_value()
        elif k == "index":
            base, size = self.array(e[1][1])
            self.index(e[2], size)
            f.mem(self.load_op(), base)
        elif k == "call":
            self.call_function(e)
        elif k == "fn":
            self.function(e)
        else:
            raise self.fail(f"internal error: cannot compile {k} to WebAssembly")

    def function(self, e):
        f, name = self.f, e[1]
        if name in ("len", "first", "last"):
            base, size = self.array(e[2][0][1])
            if name == "len":
                self.const(size)
            else:
                f.i32(0)
                f.mem(self.load_op(), base + 8 * (0 if name == "first" else size - 1))
            return
        if name == "rem":
            self.ex(e[2][0])
            self.ex(e[2][1])
            self.divide("rem")
            return
        self.ex(e[2][0])
        if name == "sqrt":
            if self.ints:
                f.call(self.rt.isqrt_u if self.uns else self.rt.isqrt)
            else:
                f.op("f64.sqrt")
        elif name == "abs":
            if self.ints:
                if not self.uns:
                    t = self.tmp()
                    f.set(t)
                    f.i64(0)
                    f.get(t)
                    f.op("i64.sub")
                    f.get(t)
                    f.get(t)
                    f.i64(0)
                    f.op("i64.lt_s", "select")
                    self.drop(t)
            else:
                f.op("f64.abs")
        elif name in ("floor", "ceil", "ceiling"):
            if not self.ints:
                f.op("f64.floor" if name == "floor" else "f64.ceil")
        else:
            raise self.fail(f"internal error: unknown function {name}")

    def binary(self, e):
        f, op = self.f, e[1]
        l, r = e[2], e[3]
        if op in ("plus", "add", "minus", "sub", "times", "mul"):
            self.ex(l)
            self.ex(r)
            base = {"plus": "add", "add": "add", "minus": "sub", "sub": "sub", "times": "mul", "mul": "mul"}[op]
            f.op(("i64." if self.ints else "f64.") + base)
        elif op in ("divide", "div", "mod", "rem") and not self.ints:
            if op in ("divide", "div"):
                self.ex(l)
                self.ex(r)
                f.op("f64.div")
            else:
                self.ex(l)
                self.ex(r)
                self.divide(op)
        elif op in ("divide", "div", "mod", "rem"):
            self.ex(l)
            c = self.const_int(r)
            if c is not None and 0 < c < (1 << 62):          # a positive constant divisor can never fail
                f.i64(c)
                if self.uns:
                    f.op("i64.div_u" if op in ("divide", "div") else "i64.rem_u")
                elif op in ("divide", "div"):
                    f.op("i64.div_s")
                elif op == "rem":
                    f.op("i64.rem_s")
                else:                                          # floor modulo
                    f.op("i64.rem_s")
                    f.i64(c)
                    f.op("i64.add")
                    f.i64(c)
                    f.op("i64.rem_s")
            else:
                self.ex(r)
                self.divide(op)
        elif op == "pow":
            self.ex(l)
            self.ex(r)
            f.call(self.rt.pow_i if self.ints else self.rt.pow_f)
        else:
            raise self.fail(f"internal error: unknown operator {op}")

    def const_int(self, e):
        if e[0] == "num" and self.ints:
            v = int(e[1]) & MASK64
            return v if v < 1 << 63 else None
        return None

    def divide(self, op):
        """the two operands are on the stack (left, right): divide, mod or rem"""
        f = self.f
        if not self.ints:                                      # floats: mod floors, rem truncates
            tb, ta = self.tmp(), self.tmp()
            f.set(tb)
            f.set(ta)
            f.get(ta)
            f.get(ta)
            f.get(tb)
            f.op("f64.div", "f64.floor" if op == "mod" else "f64.trunc")
            f.get(tb)
            f.op("f64.mul", "f64.sub")
            self.drop(ta)
            self.drop(tb)
            return
        if self.uns:
            f.call(self.rt.udiv if op in ("divide", "div") else self.rt.urem)
        elif op in ("divide", "div"):
            f.call(self.rt.sdiv)
        elif op == "mod":
            f.call(self.rt.smod)
        else:
            f.call(self.rt.srem)

    def bitop(self, e):
        f, op = self.f, e[1]
        a, b = e[2], e[3]
        if op in ("popcnt", "tzcnt", "lzcnt", "not", "bswap", "lowbit", "clearlow"):
            self.ex(a)
            if op == "popcnt":
                f.op("i64.popcnt")
            elif op == "tzcnt":
                f.op("i64.ctz")
            elif op == "lzcnt":
                f.op("i64.clz")
            elif op == "not":
                f.i64(-1)
                f.op("i64.xor")
            elif op == "bswap":
                f.call(self.rt.bswap)
            else:
                t = self.tmp()
                f.set(t)
                f.get(t)
                if op == "lowbit":
                    f.i64(0)
                    f.get(t)
                    f.op("i64.sub")
                else:
                    f.get(t)
                    f.i64(1)
                    f.op("i64.sub")
                f.op("i64.and")
                self.drop(t)
            return
        self.ex(a)
        self.ex(b)
        if op in ("and", "or", "xor"):
            f.op("i64." + op)
        elif op == "andnot":
            f.i64(-1)
            f.op("i64.xor", "i64.and")
        elif op in ("rol", "ror"):
            f.op("i64.rotl" if op == "rol" else "i64.rotr")
        elif op in ("pext", "pdep"):
            f.call(self.rt.pext if op == "pext" else self.rt.pdep)
        elif op in ("shl", "shr", "sar", "setbit", "clearbit", "flipbit"):
            c = self.const_int(b)
            if c is None or c > 63:                            # the count must be 0..63
                t = self.tmp(I64)
                f.set(t)
                f.get(t)
                f.i64(63)
                f.op("i64.gt_u")
                f.if_()
                f.call(self.rt.errs["bit"])
                f.end()
                f.get(t)
                self.drop(t, I64)
            if op in ("shl", "shr", "sar"):
                f.op({"shl": "i64.shl", "shr": "i64.shr_u", "sar": "i64.shr_s"}[op])
            else:
                t = self.tmp(I64)
                f.set(t)
                f.i64(1)
                f.get(t)
                f.op("i64.shl")                                # the one-bit mask is on the stack above the value
                if op == "setbit":
                    f.op("i64.or")
                elif op == "clearbit":
                    f.i64(-1)
                    f.op("i64.xor", "i64.and")
                else:
                    f.op("i64.xor")
                self.drop(t, I64)
        else:
            raise self.fail(f"internal error: unknown bit operation {op}")

    # ------------------------------------------------------------------ conditions (an i32 on the stack)
    def truthy(self, load):
        """is the number 'load' pushes non-zero (and not NaN)?"""
        f = self.f
        if self.ints:
            load()
            f.op("i64.eqz", "i32.eqz")
        else:
            load()
            f.f64(0.0)
            f.op("f64.ne")
            load()
            load()
            f.op("f64.eq", "i32.and")

    def cond(self, c):
        f, k = self.f, c[0]
        if k == "cmp":
            op = c[1]
            self.ex(c[2])
            self.ex(c[3])
            if self.ints:
                suffix = "" if op in ("eq", "ne") else ("_u" if self.uns else "_s")
                f.op(f"i64.{op}{suffix}")
            else:
                f.op(f"f64.{op}")
        elif k == "and":
            self.cond(c[1])
            f.if_(I32)
            self.cond(c[2])
            f.else_()
            f.i32(0)
            f.end()
        elif k == "or":
            self.cond(c[1])
            f.if_(I32)
            f.i32(1)
            f.else_()
            self.cond(c[2])
            f.end()
        elif k == "not":
            self.cond(c[1])
            f.op("i32.eqz")
        elif k == "bool":
            f.i32(1 if c[1] else 0)
        elif k in ("var", "wl"):
            self.truthy(lambda: self.ex(c))
        else:                                                  # any other number counts as yes when it is not zero
            t = self.tmp()
            self.ex(c)
            f.set(t)
            self.truthy(lambda: f.get(t))
            self.drop(t)

    # ------------------------------------------------------------------ functions
    def function_for(self, name):
        """the Func for a user function or routine (created on first use; its body is compiled later)"""
        if name in self.funcs:
            return self.funcs[name]
        if name in self.fdefs:
            d = self.fdefs[name]
            params = d[3]
            if name in self.recursive:
                pub = self.mod.func("f_" + name, [self.T] * len(params), [self.T])
                body = self.mod.func("f_" + name + "_body", [self.T] * len(params), [self.T])
                self.funcs[name] = pub
                self.funcs[name + "#body"] = body
            else:
                self.funcs[name] = self.mod.func("f_" + name, [self.T] * len(params), [self.T])
        elif name in self.routines:
            self.funcs[name] = self.mod.func("r_" + name)
        else:
            raise self.fail(f"internal error: unknown function '{name}'")
        self.pending.append(name)
        return self.funcs[name]

    def call_function(self, e):
        name = e[1][1]
        if name not in self.fdefs:
            raise self.fail(f"internal error: unknown function '{name}'")
        fn = self.function_for(name)
        for arg in e[2]:
            self.ex(arg)
        self.f.call(fn)

    def locals_of(self, d):
        names, glob = set(d[3]), set()
        for st in self.zall(d[4]):
            names.update(self.zassigned(st))
            if st[0] == "global":
                glob.update(st[2])
        return (names - glob) - {"input_ok"}

    def find_recursion(self, funcs):
        from zoomy_py import stmt_exprs, walk
        calls = {}
        for name, f in funcs.items():
            body = f[3] if f[0] == "routine" else f[4]
            c = set()
            for st in self.zall(body):
                if st[0] == "run":
                    c.add(st[2])
                for e in stmt_exprs(st):
                    walk(e, lambda x: c.add(x[1][1]) if x[0] == "call" and x[1][0] == "var" else None)
            calls[name] = c & set(funcs)
        out = set()
        for name in funcs:
            seen, todo = set(), list(calls[name])
            while todo:
                n = todo.pop()
                if n == name:
                    out.add(name)
                    break
                if n not in seen:
                    seen.add(n)
                    todo += list(calls[n])
        return out

    def compile_function(self, name):
        d = self.fdefs[name]
        pub = self.funcs[name]
        body = self.funcs.get(name + "#body", pub)
        self.node_line = d[1]
        locs = self.locals_of(d)
        self.ctx = Ctx(body, False, locs)
        for i, p in enumerate(d[3]):
            self.ctx.vars[p] = i
        self.blk(d[4])
        self.const(0)                                           # a function that reaches its end gives 0
        if name in self.recursive:
            limit = max(50, min(100000, 3_000_000 // (8 * (len(locs) + len(d[3]) + 4))))
            limit = min(limit, self.max_depth)
            f = pub
            rt = self.rt
            f.gget(self.mod.gnames["depth"])
            f.i32(1)
            f.op("i32.add")
            f.gset(self.mod.gnames["depth"])
            f.gget(self.mod.gnames["depth"])
            f.i32(limit)
            f.op("i32.gt_s")
            f.if_()
            f.call(rt.errs["deep"])
            f.end()
            for i in range(len(d[3])):
                f.get(i)
            f.call(body)
            f.gget(self.mod.gnames["depth"])
            f.i32(1)
            f.op("i32.sub")
            f.gset(self.mod.gnames["depth"])

    def compile_routine(self, name):
        r = self.routines[name]
        self.node_line = r[1]
        self.ctx = Ctx(self.funcs[name], False, set())
        self.blk(r[3])

    # ------------------------------------------------------------------ statements
    def blk(self, stmts):
        for st in stmts:
            self.stmt(st)

    def text_of_var(self, node):
        return node[1]

    def stmt(self, st):
        f, k = self.f, st[0]
        self.node_line = st[1]
        T = self.T
        if k in UNSUPPORTED:
            raise self.fail(f"{UNSUPPORTED[k]} cannot be used with the WebAssembly backend")
        if k == "set" and st[2][0] == "index":
            self.store_elem(st[2][1][1], st[2][2], st[3])
        elif k == "set":
            self.ex(st[3])
            self.vset(st[2][1])
        elif k == "aug":
            self.augment(st)
        elif k == "calc":
            self.ex(st[2])
            self.vset(st[3][1])
        elif k == "convert":
            self.convert(st)
        elif k == "alloc":
            self.allocate(st[2], int(st[3][1]), len(st) > 4 and st[4] == "shared")
        elif k == "openf":
            data = st[2][1][0].encode("utf-8", "surrogateescape")
            f.i32(self.string(data + b"\0"))
            f.i32(len(data))
            f.call(self.rt.fopen)
            self.ok_from_i32()
        elif k == "openarr":
            if not self.ints:
                raise self.fail("'open the file named by' needs integer mode")
            base, size = self.array(st[2][1])
            f.i32(base)
            f.call(self.rt.copy_path)
            t = self.tmp(I32)
            f.set(t)
            f.i32(PATH)
            f.get(t)
            f.call(self.rt.fopen)
            self.drop(t, I32)
            self.ok_from_i32()
        elif k == "closef":
            f.call(self.rt.fclose)
        elif k == "seekf":
            self.ex(st[2])
            self.to_i64()
            f.call(self.rt.fseek)
        elif k == "fsize":
            f.call(self.rt.fsize)
            self.from_i64()
            self.vset(st[2][1])
        elif k == "clock":
            if len(st) > 3:                                     # 'clock ... cores': one, there are no threads
                self.const(1)
            else:
                f.call(self.rt.clock_ms)
                self.from_i64()
            self.vset(st[2][1])
        elif k == "store":
            self.store_elem(st[2][1], st[3], st[4])
        elif k == "load":
            base, size = self.array(st[2][1])
            self.index(st[3], size)
            f.mem(self.load_op(), base)
            self.vset(st[4][1])
        elif k == "read":
            self.read(st)
        elif k == "rterror":                                # (Big Numbers rewrite) print a runtime error and stop
            failing = len(st) > 3 and st[3] == 1            # Zoomy 8: `fail with` - "zoomy: error:", exit code 1
            msg = (("zoomy: error: " if failing else "zoomy: runtime error: ") + st[2] + "\n").encode()
            f.i32(self.string(msg))
            f.i32(len(msg))
            f.i32(1 if failing else 255)
            f.call(self.rt.die)
            f.op("unreachable")
        elif k == "unread":                                 # (Big Numbers rewrite) push a character back onto the input
            self.ex(st[2])
            self.to_i64()
            f.op("i32.wrap_i64")
            f.gset(self.rt.g_pb)
        elif k == "print":
            self.aprint(st)
        elif k == "if":
            self.cond(st[2])
            f.if_()
            self.blk(st[3])
            if st[4] is not None:
                f.else_()
                self.blk(st[4])
            f.end()
        elif k == "while":
            brk, top = self.label(), self.label()
            f.block(brk)
            f.loop(top)
            self.cond(st[2])
            f.op("i32.eqz")
            f.br_if(brk)
            self.ctx.loops.append((brk, top))
            self.blk(st[3])
            self.ctx.loops.pop()
            f.br(top)
            f.end()
            f.end()
        elif k == "for":
            self.for_int(st) if self.ints else self.for_float(st)
        elif k == "foreach":
            self.foreach(st)
        elif k == "repeat":
            self.repeat(st)
        elif k == "return":
            if st[2] is None:
                f.ret()
            else:
                self.ex(st[2])
                f.ret()
        elif k == "exprstmt":
            self.ex(st[2])
            f.op("drop")
        elif k == "callstore":
            self.ex(st[2])
            self.vset(st[3][1])
        elif k in ("define", "global", "pass", "routine"):
            pass
        elif k == "stop":
            f.br(self.ctx.loops[-1][0])
        elif k == "skip":
            f.br(self.ctx.loops[-1][1])
        elif k == "scope":
            self.blk(st[2])
        elif k == "finish":
            if st[2] is None:
                f.i64(0)
            else:
                self.ex(st[2])
                self.to_i64()
            f.call(self.rt.exit_code)
            f.op("unreachable")
        elif k == "run":
            if st[2] not in self.routines:
                raise self.fail(f"unknown routine '{st[2]}'")
            f.call(self.function_for(st[2]))
        else:
            raise self.fail(f"internal error: cannot compile '{k}' to WebAssembly")

    def ok_from_i32(self):
        """an i32 flag is on the stack: input_ok = it"""
        self.bool_to_value()
        self.vset("input_ok")

    def risky(self, e):
        hit = []
        from zoomy_py import walk
        walk(e, lambda x: hit.append(1) if x[0] in ("index", "call") else None)
        return bool(hit)

    def store_elem(self, name, key, value):
        """store VALUE in ARRAY at KEY: the key and the value are worked out first, then the index is checked"""
        f = self.f
        base, size = self.array(name)
        if not self.risky(value):
            self.index(key, size)
            self.ex(value)
            f.mem(self.store_op(), base)
            return
        tk = self.tmp()
        self.ex(key)
        f.set(tk)
        tv = self.tmp()
        self.ex(value)
        f.set(tv)
        self.index(["wl", tk, False], size)
        f.get(tv)
        f.mem(self.store_op(), base)
        self.drop(tk)
        self.drop(tv)

    def augment(self, st):
        f = self.f
        op, val, tgt = st[2], st[3], st[4]
        opn = {"add": "plus", "sub": "minus", "mul": "times", "div": "divide"}[op]
        if tgt[0] == "index":
            base, size = self.array(tgt[1][1])
            tv, ta = self.tmp(), self.tmp(I32)
            self.ex(val)
            f.set(tv)
            self.index(tgt[2], size)
            f.set(ta)
            f.get(ta)
            f.get(ta)
            f.mem(self.load_op(), base)
            self.binop_stack(opn, ["wl", tv, False])
            f.mem(self.store_op(), base)
            self.drop(tv)
            self.drop(ta, I32)
            return
        name = tgt[1]
        self.vget(name)
        self.binop_stack(opn, val)
        self.vset(name)

    def binop_stack(self, opn, rhs):
        """the left operand is on the stack; apply the operator with RHS (an expression) as right operand"""
        f = self.f
        if opn in ("plus", "minus", "times"):
            self.ex(rhs)
            f.op(("i64." if self.ints else "f64.") + {"plus": "add", "minus": "sub", "times": "mul"}[opn])
        else:
            c = self.const_int(rhs)
            if self.ints and c is not None and 0 < c < (1 << 62):
                f.i64(c)
                f.op("i64.div_u" if self.uns else "i64.div_s")
            else:
                self.ex(rhs)
                if self.ints:
                    self.divide("divide")
                else:
                    f.op("f64.div")

    def convert(self, st):
        f = self.f
        if st[2] == "number":                                   # a character: keep its code, printing shows the letter
            self.ex(st[3])
            self.vset(st[4][1])
            return
        t = self.tmp(I64)
        self.ex(st[3])
        self.to_i64()
        f.i64(48)
        f.op("i64.sub")
        f.set(t)
        f.get(t)
        f.i64(9)
        f.op("i64.le_u")
        f.if_()
        f.get(t)
        self.from_i64()
        self.vset(st[4][1])
        self.set_ok(True)
        f.else_()
        self.const(0) if self.ints else f.f64(NAN)
        self.vset(st[4][1])
        self.set_ok(False)
        f.end()
        self.drop(t, I64)

    def read(self, st):
        f, rt = self.f, self.rt
        what = st[2]
        target = st[3][1]
        if what == "byte":
            f.call(rt.read_b)
            res = "i"
        elif what == "num":
            f.call(rt.read_i if self.ints else rt.read_f)
            res = "i" if self.ints else "f"
        else:
            f.call(rt.read_c)
            res = "i"
        ok = self.tmp(I32)
        f.set(ok)
        if res == "i":
            f.gget(self.mod.gnames["rvi"])
            self.from_i64()
        else:
            f.gget(self.mod.gnames["rvf"])
        self.vset(target)
        f.get(ok)
        self.ok_from_i32()
        self.drop(ok, I32)

    # ------------------------------------------------------------------ loops
    def for_float(self, st):
        f = self.f
        ta, tb, ts, tq, tn, tk = (self.tmp(F64) for _ in range(6))
        self.ex(st[3])
        f.set(ta)
        self.ex(st[4])
        f.set(tb)
        if st[5] is None:
            f.f64(1.0)
        else:
            self.ex(st[5])
        f.set(ts)
        f.get(ts); f.f64(0.0); f.op("f64.eq")
        f.get(ts); f.get(ts); f.op("f64.ne", "i32.or")
        f.if_(); f.call(self.rt.errs["step"]); f.end()
        f.get(ta); f.get(ta); f.op("f64.ne")
        f.get(tb); f.get(tb); f.op("f64.ne", "i32.or")
        f.if_(); f.call(self.rt.errs["step"]); f.end()
        f.get(tb); f.get(ta); f.op("f64.sub"); f.get(ts); f.op("f64.div"); f.set(tq)
        f.get(tq); f.f64(0.0); f.op("f64.ge")
        f.if_(F64)
        f.get(tq); f.f64(1 + 1e-12); f.op("f64.mul"); f.f64(1e-12); f.op("f64.add", "f64.floor"); f.set(tn)
        f.get(tn); f.f64(1e12); f.op("f64.ge")
        f.if_(); f.call(self.rt.errs["long"]); f.end()
        f.get(tn); f.f64(1.0); f.op("f64.add")
        f.else_()
        f.f64(0.0)
        f.end()
        f.set(tn)
        f.f64(0.0); f.set(tk)
        brk, top, cont = self.label(), self.label(), self.label()
        f.block(brk)
        f.loop(top)
        f.get(tk); f.get(tn); f.op("f64.ge"); f.br_if(brk)
        f.get(ta); f.get(tk); f.get(ts); f.op("f64.mul", "f64.add")
        self.vset(st[2])
        f.block(cont)
        self.ctx.loops.append((brk, cont))
        self.blk(st[6])
        self.ctx.loops.pop()
        f.end()
        f.get(tk); f.f64(1.0); f.op("f64.add"); f.set(tk)
        f.br(top)
        f.end()
        f.end()
        for t in (ta, tb, ts, tq, tn, tk):
            self.drop(t, F64)

    def for_int(self, st):
        f = self.f
        sv = 1 if st[5] is None else self.const_step(st[5])
        brk, top, cont = self.label(), self.label(), self.label()
        ta, tb = self.tmp(I64), self.tmp(I64)
        lt, gt = ("i64.lt_u", "i64.gt_u") if self.uns else ("i64.lt_s", "i64.gt_s")
        le, ge = ("i64.le_u", "i64.ge_u") if self.uns else ("i64.le_s", "i64.ge_s")
        if sv is not None and sv != 0:                           # a constant step: the test is at the bottom
            up = sv > 0
            self.ex(st[3]); f.set(ta)
            self.ex(st[4]); f.set(tb)
            f.block(brk)
            f.get(ta); f.get(tb); f.op(gt if up else lt); f.br_if(brk)
            f.loop(top)
            f.get(ta)
            self.vset(st[2])
            f.block(cont)
            self.ctx.loops.append((brk, cont))
            self.blk(st[6])
            self.ctx.loops.pop()
            f.end()
            if self.uns:                                         # leave the loop when the counter wraps past 0 or 2^64
                f.get(ta)
                if up:
                    f.i64(MASK64 - sv); f.op("i64.gt_u")
                else:
                    f.i64(-sv); f.op("i64.lt_u")
            else:                                                # leave it when the counter would overflow
                f.get(ta)
                if up:
                    f.i64((1 << 63) - 1 - sv); f.op("i64.gt_s")
                else:
                    f.i64(-(1 << 63) - sv); f.op("i64.lt_s")
            f.br_if(brk)
            f.get(ta); f.i64(sv); f.op("i64.add"); f.set(ta)
            f.get(ta); f.get(tb); f.op(le if up else ge); f.br_if(top)
            f.end()
            f.end()
            self.drop(ta, I64)
            self.drop(tb, I64)
            return
        ts = self.tmp(I64)
        self.ex(st[3]); f.set(ta)
        self.ex(st[4]); f.set(tb)
        if st[5] is None:
            f.i64(1)
        else:
            self.ex(st[5])
        f.set(ts)
        f.get(ts); f.op("i64.eqz")
        f.if_(); f.call(self.rt.errs["step"]); f.end()
        f.block(brk)
        f.loop(top)
        f.get(ts); f.i64(0); f.op("i64.lt_s")
        f.if_(I32)
        f.get(ta); f.get(tb); f.op(lt)
        f.else_()
        f.get(ta); f.get(tb); f.op(gt)
        f.end()
        f.br_if(brk)
        f.get(ta)
        self.vset(st[2])
        f.block(cont)
        self.ctx.loops.append((brk, cont))
        self.blk(st[6])
        self.ctx.loops.pop()
        f.end()
        f.get(ta); f.get(ts); f.op("i64.add"); f.set(ta)
        if self.uns:
            f.get(ts); f.i64(0); f.op("i64.lt_s")
            f.if_(I32)
            f.get(ta); f.get(ta); f.get(ts); f.op("i64.sub", "i64.gt_u")      # wrapped below 0: the new counter is above the old
            f.else_()
            f.get(ta); f.get(ts); f.op("i64.sub", "i64.lt_u")                 # wrapped past 2^64: the new counter is below the old
            f.end()
            f.br_if(brk)
        f.br(top)
        f.end()
        f.end()
        for t in (ta, tb, ts):
            self.drop(t, I64)

    def const_step(self, e):
        c = None
        if e[0] == "num":
            v = int(e[1]) & MASK64
            c = v - (1 << 64) if v >= 1 << 63 else v
            if not -(1 << 31) <= c < (1 << 31):
                return None
        return c

    def foreach(self, st):
        f = self.f
        base, size = self.array(st[3][1])
        tk = self.tmp(I32)
        brk, top, cont = self.label(), self.label(), self.label()
        f.i32(0); f.set(tk)
        f.block(brk)
        f.loop(top)
        f.get(tk); f.i32(size); f.op("i32.ge_u"); f.br_if(brk)
        f.get(tk); f.i32(3); f.op("i32.shl")
        f.mem(self.load_op(), base)
        self.vset(st[2])
        f.block(cont)
        self.ctx.loops.append((brk, cont))
        self.blk(st[4])
        self.ctx.loops.pop()
        f.end()
        f.get(tk); f.i32(1); f.op("i32.add"); f.set(tk)
        f.br(top)
        f.end()
        f.end()
        self.drop(tk, I32)

    def repeat(self, st):
        f = self.f
        brk, top = self.label(), self.label()
        f.block(brk)
        if st[2] is None:
            f.loop(top)
            self.ctx.loops.append((brk, top))
            self.blk(st[3])
            self.ctx.loops.pop()
            f.br(top)
            f.end()
            f.end()
            return
        tc = self.tmp(I64)
        self.ex(st[2])
        self.to_i64()
        f.set(tc)
        if not self.uns:
            f.get(tc); f.i64(0); f.op("i64.lt_s")
            f.if_(); f.call(self.rt.errs["count"]); f.end()
        f.loop(top)
        f.get(tc)
        if self.uns:
            f.op("i64.eqz")
        else:
            f.i64(0)
            f.op("i64.le_s")
        f.br_if(brk)
        f.get(tc); f.i64(1); f.op("i64.sub"); f.set(tc)
        self.ctx.loops.append((brk, top))
        self.blk(st[3])
        self.ctx.loops.pop()
        f.br(top)
        f.end()
        f.end()
        self.drop(tc, I64)

    # ------------------------------------------------------------------ printing
    def write_bytes(self, data):
        if data:
            self.f.i32(self.string(data))
            self.f.i32(len(data))
            self.f.call(self.rt.wbytes)

    def write_char(self, e):
        self.ex(e)
        self.to_i64()
        self.f.op("i32.wrap_i64")
        self.f.call(self.rt.put)

    def write_flag(self, e):
        f = self.f
        self.cond(e)
        f.if_()
        self.write_bytes(b"yes")
        f.else_()
        self.write_bytes(b"no")
        f.end()

    def write_num(self, e):
        self.ex(e)
        self.f.call((self.rt.print_u64 if self.uns else self.rt.print_i64) if self.ints else self.rt.print_f64)

    def pre(self, e):
        """work out e now into a hidden variable (so an error in a later part of the line shows nothing of it)"""
        t = self.f.local(self.T)
        self.ex(e)
        self.f.set(t)
        return ["wl", t, self.is_flag(e)]

    def print_segment(self, seg, newline):
        parts = []
        for e in seg:
            if e[0] == "str":
                parts += list(e[1])
            else:
                parts.append(e)
        if any(self.risky(p) for p in parts if not isinstance(p, str)):
            new = []
            for p in parts:
                if isinstance(p, str) or (p[0] == "var" and p[1] in self.char_vars) or p[0] == "num":
                    new.append(p)
                else:
                    new.append(self.pre(p))
            parts = new
        pending = b""
        for p in parts:
            if isinstance(p, str):
                pending += p.encode("utf-8", "surrogateescape")
                continue
            self.write_bytes(pending)
            pending = b""
            if p[0] == "var" and p[1] in self.char_vars:
                self.write_char(p)
            elif self.is_flag(p):
                self.write_flag(p)
            else:
                self.write_num(p)
        if newline:
            pending += b"\n"
        self.write_bytes(pending)

    def aprint(self, st):
        seg = []
        for kind, e in st[3]:
            if kind == "char":
                self.print_segment(seg, False)
                seg = []
                self.write_char(e)
            else:
                seg.append(e)
        self.print_segment(seg, bool(st[2]))

    # ------------------------------------------------------------------ the whole program
    def compile(self):
        prog = self.prog
        for s in prog.stmts:
            if s[0] == "routine":
                self.routines[s[2]] = s
            elif s[0] == "define":
                self.fdefs[s[2]] = s
        self.recursive = self.find_recursion({**self.routines, **self.fdefs})
        shared = {"input_ok"}
        for s in list(self.routines.values()) + list(self.fdefs.values()):
            _strings_in(s, shared)
        main = []
        for s in prog.stmts:
            if s[0] == "action":
                main += s[2]
            elif s[0] not in ("routine", "define", "use", "usefrom", "extern"):
                main.append(s)
        names = set()
        _strings_in(main, names)
        start = self.mod.func("_start", export="_start")
        self.ctx = Ctx(start, True, names - shared)
        self.blk(main)
        start.call(self.rt.flush)
        main_ctx = self.ctx
        while self.pending:
            name = self.pending.pop(0)
            if name in self.fdefs:
                self.compile_function(name)
            else:
                self.compile_routine(name)
        self.ctx = main_ctx
        total = max(self.arr_end, self.str_end)
        self.mod.pages = max(1, -(-total // 65536))
        if self.mod.pages > 32768:
            raise self.fail("the program needs more than 2 GB of memory")
        return self.mod.encode()


def compile_program(prog, max_depth=MAX_DEPTH):
    """the statement tree of a native-subset program -> the bytes of a WebAssembly (WASI) module"""
    return WasmCompiler(prog, max_depth).compile()


# =============================================================================
# 4. Running and packaging a module
# =============================================================================
def find_runner(path, args=()):
    """a command line that runs the module here: Node.js (with zoomy_wasm_host.js beside this file), else wasmtime or wasmer"""
    import os
    import shutil
    host = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zoomy_wasm_host.js")
    node = shutil.which("node") or shutil.which("nodejs")
    if node and os.path.isfile(host):
        return [node, host, path] + list(args)
    for tool, pre in (("wasmtime", ["run", "--dir=."]), ("wasmer", ["run", "--dir=."])):
        exe = shutil.which(tool)
        if exe:
            return [exe] + pre + [path] + list(args)
    return None


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --bg:#fbfbfa; --fg:#1c1c1a; --mut:#6b6b66; --box:#fff; --line:#d9d9d3; --acc:#2c5fd1; --err:#b3261e; }
@media (prefers-color-scheme: dark) { :root { --bg:#161615; --fg:#ecece8; --mut:#9a9a93; --box:#1f1f1d; --line:#35352f; --acc:#7aa2ff; --err:#ff8a80; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, sans-serif; }
main { max-width:760px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:1.25rem; margin:0 0 4px; }
p.sub { margin:0 0 20px; color:var(--mut); font-size:.9rem; }
label { display:block; font-size:.85rem; color:var(--mut); margin:16px 0 6px; }
textarea, pre { width:100%; background:var(--box); color:var(--fg); border:1px solid var(--line); border-radius:8px; padding:10px 12px;
  font:14px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; margin:0; }
textarea { min-height:5.5em; resize:vertical; }
pre { min-height:8em; white-space:pre-wrap; word-break:break-word; overflow:auto; }
pre .err { color:var(--err); }
button { margin-top:14px; background:var(--acc); color:#fff; border:0; border-radius:8px; padding:9px 18px; font:inherit; cursor:pointer; }
button:disabled { opacity:.5; cursor:default; }
#status { display:inline-block; margin-left:12px; color:var(--mut); font-size:.9rem; }
</style>
</head>
<body>
<main>
<h1>__TITLE__</h1>
<p class="sub">A Zoomy program, compiled to WebAssembly. It runs in this page; nothing is sent anywhere.</p>
<label for="inp">Input for the program (what it reads with 'read'; leave empty if it reads nothing)</label>
<textarea id="inp" spellcheck="false"></textarea>
<button id="run">Run</button><span id="status"></span>
<label for="out">Output</label>
<pre id="out"></pre>
</main>
<script>
const WASM_B64 = "__WASM__";
const WORKER = `__WORKER__`;
const out = document.getElementById("out"), status = document.getElementById("status"), btn = document.getElementById("run");
function add(text, cls) {
  if (!text) return;
  if (cls) { const s = document.createElement("span"); s.className = cls; s.textContent = text; out.appendChild(s); }
  else out.appendChild(document.createTextNode(text));
}
btn.onclick = () => {
  out.textContent = ""; btn.disabled = true; status.textContent = "running...";
  const bytes = Uint8Array.from(atob(WASM_B64), c => c.charCodeAt(0));
  const w = new Worker(URL.createObjectURL(new Blob([WORKER], { type: "text/javascript" })));
  const dec = [null, new TextDecoder(), new TextDecoder()];
  w.onmessage = (e) => {
    const m = e.data;
    if (m.fd) add(dec[m.fd].decode(m.data, { stream: true }), m.fd === 2 ? "err" : "");
    else if (m.done) {
      status.textContent = m.error ? "stopped" : "finished, exit code " + m.code;
      if (m.error) add("\n" + m.error + "\n", "err");
      btn.disabled = false; w.terminate();
    }
  };
  w.postMessage({ wasm: bytes, input: document.getElementById("inp").value }, [bytes.buffer]);
};
</script>
</body>
</html>
"""

WORKER_JS = r"""
self.onmessage = async (ev) => {
  const input = new TextEncoder().encode(ev.data.input);
  let pos = 0, mem = null;
  class Exit { constructor(code) { this.code = code; } }
  const dv = () => new DataView(mem.buffer);
  const wasi = {
    fd_write(fd, iovs, n, nw) {
      const d = dv(); let total = 0;
      for (let i = 0; i < n; i++) {
        const p = d.getUint32(iovs + 8 * i, true), l = d.getUint32(iovs + 8 * i + 4, true);
        self.postMessage({ fd: fd === 2 ? 2 : 1, data: new Uint8Array(mem.buffer.slice(p, p + l)) });
        total += l;
      }
      d.setUint32(nw, total, true); return 0;
    },
    fd_read(fd, iovs, n, nr) {
      if (fd !== 0) return 8;
      const d = dv(); let total = 0;
      for (let i = 0; i < n; i++) {
        const p = d.getUint32(iovs + 8 * i, true), l = d.getUint32(iovs + 8 * i + 4, true);
        const k = Math.min(l, input.length - pos);
        new Uint8Array(mem.buffer, p, k).set(input.subarray(pos, pos + k)); pos += k; total += k;
        if (k < l) break;
      }
      d.setUint32(nr, total, true); return 0;
    },
    proc_exit(code) { throw new Exit(code); },
    clock_time_get(id, prec, out) { dv().setBigUint64(out, BigInt(Math.round(performance.now() * 1e6)), true); return 0; },
    path_open() { return 44; },
    fd_seek() { return 70; },
    fd_close() { return 0; },
  };
  try {
    const { instance } = await WebAssembly.instantiate(ev.data.wasm, { wasi_snapshot_preview1: wasi });
    mem = instance.exports.memory;
    instance.exports._start();
    self.postMessage({ done: true, code: 0 });
  } catch (e) {
    if (e instanceof Exit) self.postMessage({ done: true, code: e.code });
    else if (e instanceof RangeError) self.postMessage({ done: true, error: "zoomy: runtime error: too many nested calls (a function calls itself without stopping?)" });
    else self.postMessage({ done: true, error: "zoomy: " + e.message });
  }
};
"""


def html_page(title, wasm):
    """one self-contained web page that holds the module and runs it (in a worker, so the page stays responsive)"""
    import base64
    import html
    page = HTML_TEMPLATE.replace("__WORKER__", WORKER_JS.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${"))
    page = page.replace("__WASM__", base64.b64encode(wasm).decode()).replace("__TITLE__", html.escape(title))
    return page
