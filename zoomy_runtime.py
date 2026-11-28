# ---------------------------------------------------------------------------------------
# Zoomy runtime for the Python backend.
# This file is copied verbatim to the top of every program that `zoomy.py` compiles to Python,
# so a compiled program is one standalone .py file that needs only Python 3.8+.
# ---------------------------------------------------------------------------------------
import math as _zmath
import os as _zos
import random as _zrandom
import struct as _zstruct
import sys as _zsys
import time as _ztime

_INF = float("inf")
_NAN = float("nan")


class ZoomyFailure(Exception):
    """Raised by `fail with ...` and `check that ...`."""


class ZoomyRuntimeError(Exception):
    """A runtime error with a friendly message."""


# ---------------------------------------------------------------------------- output
_zout = _zsys.stdout.buffer
try:
    _ztty = _zsys.stdout.isatty()
except Exception:                                          # pragma: no cover
    _ztty = False


def _zflush():
    try:
        _zout.flush()
    except Exception:                                      # e.g. closed pipe
        pass


def _zw(s):
    _zout.write(s.encode("utf-8", "surrogateescape"))
    if _ztty:
        _zflush()


def _zwb(x):
    _zout.write(bytes([_zint64(x) & 255]))
    if _ztty:
        _zflush()


def _zexit(code=0):
    _zflush()
    raise SystemExit(code)


# ---------------------------------------------------------------------------- numbers
def _zint64(x):
    """cvttsd2si: truncate toward zero; NaN / out of range -> 0x8000000000000000."""
    if type(x) is int and _ZINTS:
        return x
    if type(x) is _BD:
        return int(x)
    try:
        x = float(x)
    except (TypeError, ValueError):
        raise ZoomyRuntimeError("expected a number but got " + _zkind(x))
    if x != x or abs(x) >= 9.223372036854775808e18:
        return -(1 << 63)
    return int(x)


def _zdiv(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        if a != a or a == 0:
            return _NAN
        neg = (_zmath.copysign(1.0, a) < 0) != (_zmath.copysign(1.0, b) < 0)
        return -_INF if neg else _INF
    except OverflowError:
        return _INF


def _zmod(a, b):                                           # a - b * floor(a / b)
    return a - b * _zfloor(_zdiv(a, b))


def _zpow(a, b):
    """Whole exponents: exponentiation by squaring (same steps as the native runtime); others: math.pow."""
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise ZoomyRuntimeError("'to the power of' needs two numbers but got %s and %s" % (_zkind(a), _zkind(b)))
    a, b = float(a), float(b)
    if b == b and abs(b) < 9.223372036854775808e18 and b == _zmath.floor(b):
        n, r, x = int(abs(b)), 1.0, a
        while n:
            if n & 1:
                r *= x
            x *= x
            n >>= 1
        return _zdiv(1.0, r) if _zmath.copysign(1.0, b) < 0 else r
    try:
        return _zmath.pow(a, b)
    except ValueError:
        return _NAN
    except OverflowError:
        neg = a < 0 and b == _zmath.floor(b) and int(b) % 2 == 1
        return -_INF if neg else _INF


def _zsqrt(x):
    x = float(x)
    if x != x:
        return x
    if x < 0:
        return _NAN
    return _zmath.sqrt(x)


def _zsround(x, fn):
    x = float(x)
    if x != x or x in (_INF, -_INF):
        return x
    r = float(fn(x))
    return _zmath.copysign(0.0, x) if r == 0 else r


def _zfloor(x):
    return _zsround(x, _zmath.floor)


def _zceil(x):
    return _zsround(x, _zmath.ceil)


def _zrem(a, b):                                           # remainder with the sign of a (C fmod)
    q = _zsround(_zdiv(a, b), _zmath.trunc)
    return a - b * q


def _zround(x):                                            # halves round away from zero: 2.5 -> 3
    x = float(x)
    if x != x or x in (_INF, -_INF):
        return x
    return _zmath.copysign(_zmath.floor(abs(x) + 0.5), x)


def _zrounded(x, n):
    x, n = float(x), int(n)
    if x != x or x in (_INF, -_INF):
        return x
    p = 10.0 ** n
    return _zmath.copysign(_zmath.floor(abs(x) * p + 0.5) / p, x)


def _zln(x):
    x = float(x)
    if x != x or x < 0:
        return _NAN
    if x == 0:
        return -_INF
    return _zmath.log(x)


def _zexp(x):
    try:
        return _zmath.exp(x)
    except OverflowError:
        return _INF


def _zsin(x):
    try:
        return _zmath.sin(x)
    except ValueError:
        return _NAN


def _zcos(x):
    try:
        return _zmath.cos(x)
    except ValueError:
        return _NAN


def _ztan(x):
    try:
        return _zmath.tan(x)
    except ValueError:
        return _NAN


def _zatan(x):
    return _zmath.atan(x)


def _zcount(x):
    n = _zint64(x)
    if n < 0:
        raise ZoomyRuntimeError("a count cannot be negative")
    return n


def _zfrange(a, b, s):
    a, b, s = float(a), float(b), float(s)
    if s == 0 or s != s or a != a or b != b:
        raise ZoomyRuntimeError("a 'for' loop needs a step that is not zero")
    q = (b - a) / s
    n = 0
    if q >= 0:
        t = q * (1 + 1e-12) + 1e-12
        if t >= 1e12:
            raise ZoomyRuntimeError("this 'for' loop would run too long")
        n = _zmath.floor(t) + 1
    i = 0
    while i < n:
        yield a + i * s
        i += 1


# ---------------------------------------------------------------------------- integer mode (Zoomy 5.5)
_ZINTS = False
_ZUNS = False
_M64 = 0xFFFFFFFFFFFFFFFF
_ZW = 64                                                   # bits in a whole number: 64, or 1024 for Big Numbers (Zoomy 7)


def _zset_ints(unsigned=False, big=False):
    global _ZINTS, _ZUNS, _M64, _ZW
    _ZINTS = True
    _ZUNS = bool(unsigned)
    if big:
        _ZW = 1024
        _M64 = (1 << 1024) - 1


def _ziw(x):
    """wrap to a signed 64-bit integer (like the machine does); to 0 .. 2^64-1 in unsigned mode"""
    if type(x) is int:
        x &= _M64
        if _ZUNS:
            return x
        return x - (1 << _ZW) if x >> (_ZW - 1) else x
    return x


def _zsigned(x):
    return x - (1 << _ZW) if x >> (_ZW - 1) else x


def _zidiv(a, b):                                          # truncating division
    if b == 0:
        raise ZoomyRuntimeError("division by zero")
    q = abs(a) // abs(b)
    return _ziw(-q if (a < 0) != (b < 0) else q)


def _zimod(a, b):                                          # a - b * floor(a / b)
    if b == 0:
        raise ZoomyRuntimeError("division by zero")
    return a % b


def _zirem(a, b):                                          # remainder with the sign of a
    if b == 0:
        raise ZoomyRuntimeError("division by zero")
    return _ziw(a - b * _zidiv(a, b))


def _zipow(a, b):
    if b < 0:
        if a == 1:
            return 1
        if a == -1:
            return 1 if b % 2 == 0 else -1
        if a == 0:
            raise ZoomyRuntimeError("division by zero")
        return 0
    r = 1
    while b:
        if b & 1:
            r = _ziw(r * a)
        a = _ziw(a * a)
        b >>= 1
    return r


def _zisqrt(a):
    return _zmath.isqrt(a) if a > 0 else 0


def _zinum(x):
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return int(x)
    if isinstance(x, str):
        try:
            return int(x.strip())
        except ValueError:
            pass
    raise ZoomyRuntimeError("cannot turn %s into a whole number" % (_zquote(x) if isinstance(x, str) else _zkind(x)))


def _zirange(a, b, s):
    a, b, s = int(a), int(b), int(s)
    if _ZUNS and s >> 63:                                      # a step with the top bit set counts down
        s -= 1 << 64
    if s == 0:
        raise ZoomyRuntimeError("a 'for' loop needs a step that is not zero")
    return range(a, b + 1, s) if s > 0 else range(a, b - 1, s)


def _zread_inum():
    while True:
        c = _zgetc()
        if c == -1:
            return 0, 0
        if not _zws(c):
            break
    neg = False
    if c == 45:
        neg, c = True, _zgetc()
    elif c == 43:
        c = _zgetc()
    m, digits = 0, 0
    while c != -1:
        if 48 <= c <= 57:
            m = _ziw(m * 10 + (c - 48))
            digits += 1
            c = _zgetc()
        else:
            _zin.pb = c
            break
    if digits == 0:
        _zin.pb = -1
        return 0, 0
    return (_ziw(-m) if neg else m), 1


def _zbit(op, a, b=None):
    """the bitwise operations (integer mode): a and b are 64-bit signed integers"""
    if type(a) is not int or (b is not None and type(b) is not int):
        raise ZoomyRuntimeError("bitwise operations need whole numbers (use 'from now on, use integers instead of floats')")
    if op == "and":
        return a & b
    if op == "or":
        return a | b
    if op == "xor":
        return a ^ b
    if op == "andnot":
        return _ziw(a & ~b)
    if op in ("pext", "pdep"):
        u, m, out, k = a & _M64, b & _M64, 0, 0
        for i in range(_ZW):
            if (m >> i) & 1:
                if op == "pext":
                    out |= ((u >> i) & 1) << k
                else:
                    out |= ((u >> k) & 1) << i
                k += 1
        return _ziw(out)
    if op in ("shl", "shr", "sar", "rol", "ror", "setbit", "clearbit", "flipbit"):
        n = b & (_ZW - 1) if op in ("rol", "ror") else b
        if not 0 <= n <= _ZW - 1:
            raise ZoomyRuntimeError("a shift or bit number must be from 0 to %d" % (_ZW - 1))
        u = a & _M64
        if op == "shl":
            return _ziw(u << n)
        if op == "shr":
            return _ziw(u >> n)
        if op == "sar":
            return _ziw(_zsigned(u) >> n)
        if op == "rol":
            return _ziw((u << n) | (u >> (_ZW - n)))
        if op == "ror":
            return _ziw((u >> n) | (u << (_ZW - n)))
        if op == "setbit":
            return _ziw(u | (1 << n))
        if op == "clearbit":
            return _ziw(u & ~(1 << n))
        return _ziw(u ^ (1 << n))
    u = a & _M64
    if op == "not":
        return _ziw(~a)
    if op == "popcnt":
        return bin(u).count("1")
    if op == "tzcnt":
        return _ZW if u == 0 else (u & -u).bit_length() - 1
    if op == "lzcnt":
        return _ZW - u.bit_length()
    if op == "bswap":
        return _ziw(int.from_bytes(u.to_bytes(_ZW // 8, "little"), "big"))
    if op == "lowbit":
        return _ziw(u & -u)
    if op == "clearlow":
        return _ziw(u & (u - 1))
    raise ZoomyRuntimeError("unknown bit operation " + op)


# ---------------------------------------------------------------------------- Big Decimals (Zoomy 7)
# A Big Decimal is  (-1)^sign * m * 2^e  with m a whole number of exactly 1024 bits (or 0 for zero): binary floating point with a
# 1024-bit mantissa, about 308 decimal digits, and a binary exponent. Every operation is computed exactly and then cut (not
# rounded) to 1024 bits. Adding two numbers whose exponents differ by more than 1100 gives the bigger one. A value must stay below
# 2**2048 (an error) and below 2**-2048 it becomes 0. The native and WebAssembly compilers do the very same steps (in Zoomy).
_ZBD = False
_BD_BITS = 1024
_BD_ALIGN = 1100
_BD_EMAX = 1024                                            # largest exponent of m  (value < 2**2048)
_BD_EMIN = -3072                                           # smaller than this: the value is 0
_BD_DIGITS = 110                                           # significant digits printed


class _BD(object):
    __slots__ = ("s", "m", "e")

    def __init__(self, s, m, e):
        self.s, self.m, self.e = s, m, e

    def __repr__(self):
        return "_BD(%s)" % _bd_str(self)

    # arithmetic: another number (a whole Python number, a float, a _BD) is turned into a _BD first
    def __add__(self, o):
        return _bd_add(self, _bd_coerce(o))

    __radd__ = __add__

    def __sub__(self, o):
        return _bd_add(self, _bd_neg(_bd_coerce(o)))

    def __rsub__(self, o):
        return _bd_add(_bd_coerce(o), _bd_neg(self))

    def __mul__(self, o):
        return _bd_mul(self, _bd_coerce(o))

    __rmul__ = __mul__

    def __truediv__(self, o):
        return _bd_div(self, _bd_coerce(o))

    def __rtruediv__(self, o):
        return _bd_div(_bd_coerce(o), self)

    def __neg__(self):
        return _bd_neg(self)

    def __pos__(self):
        return self

    def __abs__(self):
        return _BD(0, self.m, self.e) if self.m else self

    def __bool__(self):
        return self.m != 0

    def _key(self):
        if self.m == 0:
            return (0, 0, 0)
        return (-1 if self.s else 1, (self.e if not self.s else -self.e), self.m if not self.s else -self.m)

    def __eq__(self, o):
        try:
            o = _bd_coerce(o)
        except ZoomyRuntimeError:
            return NotImplemented
        return (self.s, self.m, self.e) == (o.s, o.m, o.e)

    def __ne__(self, o):
        r = self.__eq__(o)
        return r if r is NotImplemented else not r

    def __lt__(self, o):
        return _bd_cmp(self, _bd_coerce(o)) < 0

    def __le__(self, o):
        return _bd_cmp(self, _bd_coerce(o)) <= 0

    def __gt__(self, o):
        return _bd_cmp(self, _bd_coerce(o)) > 0

    def __ge__(self, o):
        return _bd_cmp(self, _bd_coerce(o)) >= 0

    def __hash__(self):
        return hash((self.s, self.m, self.e))

    def __float__(self):
        if self.m == 0:
            return 0.0
        try:
            v = _zmath.ldexp(float(self.m >> (_BD_BITS - 60)), self.e + _BD_BITS - 60)
        except OverflowError:
            v = _INF
        return -v if self.s else v

    def __int__(self):
        i, _ = _bd_intpart(self)
        return -i if self.s else i

    def __index__(self):
        i, frac = _bd_intpart(self)
        if frac:
            raise ZoomyRuntimeError("expected a whole number but got " + _bd_str(self))
        return -i if self.s else i


_BD_ZERO = _BD(0, 0, 0)


def _bd_make(s, n, e):
    """the number n * 2**e (n >= 0 a whole number), cut to 1024 bits"""
    if n == 0:
        return _BD_ZERO
    ln = n.bit_length()
    if ln > _BD_BITS:
        n >>= ln - _BD_BITS
        e += ln - _BD_BITS
    elif ln < _BD_BITS:
        n <<= _BD_BITS - ln
        e -= _BD_BITS - ln
    if e > _BD_EMAX:
        raise ZoomyRuntimeError("a Big Decimal got too large (more than about 1e616)")
    if e < _BD_EMIN:
        return _BD_ZERO
    return _BD(s, n, e)


def _bd_from_int(v):
    return _bd_make(1 if v < 0 else 0, abs(v), 0)


def _bd_from_fraction(num, den):
    """num / den (den > 0), cut toward zero"""
    s = 1 if num < 0 else 0
    num = abs(num)
    if num == 0:
        return _BD_ZERO
    t = max(0, _BD_BITS + 6 + den.bit_length() - num.bit_length())
    return _bd_make(s, (num << t) // den, -t)


def _bd_from_text(text):
    """a decimal number written as text ('0.1', '-6.62607015e-34'), exactly as the compiler reads it"""
    import fractions
    f = fractions.Fraction(text)
    return _bd_from_fraction(f.numerator, f.denominator)


_bd_cache = {}


def _bdlit(n, d):
    k = (n, d)
    v = _bd_cache.get(k)
    if v is None:
        v = _bd_cache[k] = _bd_from_fraction(n, d)
    return v


def _bd_coerce(o):
    if type(o) is _BD:
        return o
    if isinstance(o, bool):
        return _bd_from_int(int(o))
    if isinstance(o, int):
        return _bd_from_int(o)
    if isinstance(o, float):
        if o != o or o in (_INF, -_INF):
            raise ZoomyRuntimeError("a Big Decimal cannot hold infinity or not-a-number")
        n, d = o.as_integer_ratio()
        return _bd_from_fraction(n, d)
    raise ZoomyRuntimeError("expected a number but got " + _zkind(o))


def _bd_neg(x):
    return _BD(1 - x.s, x.m, x.e) if x.m else x


def _bd_cmp(a, b):
    ka, kb = a._key(), b._key()
    return (ka > kb) - (ka < kb)


def _bd_add(a, b):
    if a.m == 0:
        return b
    if b.m == 0:
        return a
    gap = a.e - b.e
    if gap > _BD_ALIGN:
        return a
    if gap < -_BD_ALIGN:
        return b
    e0 = min(a.e, b.e)
    x = (a.m << (a.e - e0)) * (-1 if a.s else 1) + (b.m << (b.e - e0)) * (-1 if b.s else 1)
    return _bd_make(1 if x < 0 else 0, abs(x), e0)


def _bd_mul(a, b):
    if a.m == 0 or b.m == 0:
        return _BD_ZERO
    return _bd_make(a.s ^ b.s, a.m * b.m, a.e + b.e)


def _bd_div(a, b):
    if b.m == 0:
        raise ZoomyRuntimeError("division by zero")
    if a.m == 0:
        return _BD_ZERO
    return _bd_make(a.s ^ b.s, (a.m << _BD_BITS) // b.m, a.e - b.e - _BD_BITS)


def _bd_intpart(x):
    """(the whole part of |x|, whether |x| has a fractional part)"""
    if x.m == 0:
        return 0, False
    if x.e >= 0:
        return x.m << x.e, False
    sh = -x.e
    if sh > _BD_BITS:
        return 0, True
    return x.m >> sh, (x.m & ((1 << sh) - 1)) != 0


def _bd_floor(x):
    x = _bd_coerce(x)
    i, frac = _bd_intpart(x)
    return _bd_from_int(-(i + frac) if x.s else i)


def _bd_ceil(x):
    x = _bd_coerce(x)
    i, frac = _bd_intpart(x)
    return _bd_from_int(-i if x.s else i + frac)


def _bd_trunc(x):
    i, _ = _bd_intpart(x)
    return _bd_from_int(-i if x.s else i)


def _bd_round(x):                                          # halves round away from zero
    x = _bd_coerce(x)
    if x.m == 0:
        return x
    i, _ = _bd_intpart(x)
    sh = -x.e
    if 1 <= sh <= _BD_BITS and (x.m >> (sh - 1)) & 1:
        i += 1
    return _bd_from_int(-i if x.s else i)


def _bd_mod(a, b):                                         # a - b * floor(a / b)
    a, b = _bd_coerce(a), _bd_coerce(b)
    return a - b * _bd_floor(a / b)


def _bd_rem(a, b):                                         # the remainder with the sign of a
    a, b = _bd_coerce(a), _bd_coerce(b)
    return a - b * _bd_trunc(a / b)


def _bd_sqrt(x):
    x = _bd_coerce(x)
    if x.m == 0:
        return x
    if x.s:
        raise ZoomyRuntimeError("the square root of a negative number")
    m, e = x.m, x.e
    if e & 1:
        m <<= 1
        e -= 1
    return _bd_make(0, _zmath.isqrt(m << _BD_BITS), (e - _BD_BITS) // 2)


def _bd_pow(a, b):
    a, b = _bd_coerce(a), _bd_coerce(b)
    n, frac = _bd_intpart(b)
    if frac:
        raise ZoomyRuntimeError("Big Decimals can only be raised to whole-number powers")
    r, x = _bd_from_int(1), a
    k = n
    while k:
        if k & 1:
            r = _bd_mul(r, x)
        k >>= 1
        if k:
            x = _bd_mul(x, x)
    return _bd_div(_bd_from_int(1), r) if b.s and n else r


def _bd_str(x):
    """the number as plain decimal text: at most 110 significant digits (rounded), no trailing zeros, never an exponent"""
    if x.m == 0:
        return "0"
    i, _ = _bd_intpart(x)
    D = _BD_DIGITS
    digs = list(str(i)) if i else []
    point = len(digs)                                      # digits before the decimal point
    if x.e < 0:
        k = -x.e
        f = x.m & ((1 << k) - 1) if k <= _BD_BITS else x.m
        zeros = 0
        started = bool(digs)
        while f and len(digs) < D + 1:
            f *= 10
            d = f >> k
            f &= (1 << k) - 1
            if not started:
                if d == 0:
                    zeros += 1
                    continue
                started = True
            digs.append(str(d))
        if not point:
            point = -zeros
    if len(digs) > D:
        up = int(digs[D]) >= 5
        digs = digs[:D]
        if up:
            j = D - 1
            while j >= 0 and digs[j] == "9":
                digs[j] = "0"
                j -= 1
            if j < 0:
                digs = ["1"] + digs[:-1]
                point += 1
            else:
                digs[j] = str(int(digs[j]) + 1)
    s = "".join(digs)
    if point >= len(s):
        out = s + "0" * (point - len(s))
    elif point > 0:
        out = s[:point] + "." + s[point:]
    else:
        out = "0." + "0" * (-point) + s
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return ("-" if x.s else "") + out


def _bd_toint(x):
    """a whole Big Decimal as a Python int (an error when it has a fraction)"""
    return x.__index__()


def _bd_range(a, b, s):
    a, b, s = _bd_coerce(a), _bd_coerce(b), _bd_coerce(s)
    if s.m == 0:
        raise ZoomyRuntimeError("a 'for' loop needs a step that is not zero")
    q = (b - a) / s
    n = 0
    if q.s == 0:
        t = _bd_floor(q + _BD_EPS)
        n = _bd_toint(t) + 1
        if n >= 1 << 40:
            raise ZoomyRuntimeError("this 'for' loop would run too long")
    i = 0
    while i < n:
        yield a + _bd_from_int(i) * s
        i += 1


_BD_EPS = _bd_from_text("1e-100")


def _bd_read_num():
    while True:
        c = _zgetc()
        if c == -1:
            return _BD_ZERO, 0
        if not _zws(c):
            break
    neg = False
    if c == 45:
        neg, c = True, _zgetc()
    elif c == 43:
        c = _zgetc()
    m, digits, frac, extra, dot = 0, 0, 0, 0, False
    while c != -1:
        if 48 <= c <= 57:
            digits += 1
            if digits <= 300:
                m = m * 10 + (c - 48)
                if dot:
                    frac += 1
            elif not dot:
                extra += 1
            c = _zgetc()
        elif c == 46 and not dot:
            dot = True
            c = _zgetc()
        else:
            _zin.pb = c
            break
    if digits == 0:
        _zin.pb = -1
        return _BD_ZERO, 0
    v = _bd_from_int(m)
    if frac:
        v = _bd_div(v, _bd_pow(_bd_from_int(10), _bd_from_int(frac)))
    elif extra:
        v = _bd_mul(v, _bd_pow(_bd_from_int(10), _bd_from_int(extra)))
    return (_bd_neg(v) if neg else v), 1



def _zset_bd():
    global _ZBD
    _ZBD = True


# ---------------------------------------------------------------------------- number -> text
def _zfmt(x):
    """Zoomy's number format: up to 6 decimals, scientific below 1e-6 / from 1e15."""
    try:
        x = float(x)
    except OverflowError:
        return "inf" if x > 0 else "-inf"
    if x != x:
        return "nan"
    bits = _zstruct.unpack("<Q", _zstruct.pack("<d", x))[0]
    sign = bits >> 63
    bits &= ~(1 << 63)
    a = _zstruct.unpack("<d", _zstruct.pack("<Q", bits))[0]
    if bits == 0x7FF0000000000000:
        return "-inf" if sign else "inf"
    if bits == 0:
        return "0"
    out = "-" if sign else ""
    if 0x3EB0C6F7A0B5ED8D <= bits < 0x430C6BF526340000:
        ip = int(a)
        fd = round((a - float(ip)) * 1e6)
        if fd >= 1000000:
            ip += 1
            fd -= 1000000
        out += str(ip)
        if fd:
            out += "." + ("%06d" % fd).rstrip("0")
        return out
    e, m = 0, a
    while m >= 10.0:
        m /= 10.0
        e += 1
    while m < 1.0:
        m *= 10.0
        e -= 1
    ip = int(m)
    fd = round((m - float(ip)) * 1e6)
    if fd >= 1000000:
        ip += 1
        fd -= 1000000
    if ip >= 10:
        ip, e = 1, e + 1
    out += str(ip)
    if fd:
        out += "." + ("%06d" % fd).rstrip("0")
    return out + "e" + ("-" if e < 0 else "+") + ("0" if abs(e) < 10 else "") + str(abs(e))


def _zquote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def _zshow(x, inner=False):
    if x is None:
        return "nothing"
    if x is True:
        return "yes"
    if x is False:
        return "no"
    if isinstance(x, str):
        return _zquote(x) if inner else x
    if type(x) is _BD:
        return _bd_str(x)
    if _ZBD and isinstance(x, (int, float)):
        return str(x) if isinstance(x, int) else _bd_str(_bd_coerce(x))
    if _ZINTS and isinstance(x, int):
        return str(x)
    if isinstance(x, (int, float)):
        return _zfmt(x)
    if isinstance(x, list):
        return "[" + ", ".join(_zshow(i, True) for i in x) + "]"
    if isinstance(x, tuple):
        return "(" + ", ".join(_zshow(i, True) for i in x) + ")"
    if isinstance(x, dict):
        if not x:
            return "empty table"
        return "table with " + " and ".join(_zshow(k, True) + " as " + _zshow(v, True) for k, v in x.items())
    try:
        import numbers
        if isinstance(x, numbers.Real):
            return _zfmt(x)
    except Exception:                                      # pragma: no cover
        pass
    return str(x)


def _znum(x):
    if type(x) is _BD:
        return x
    if _ZBD:
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return _bd_coerce(x)
        if isinstance(x, str):
            try:
                return _bd_from_text(x.strip())
            except (ValueError, ZeroDivisionError):
                pass
        raise ZoomyRuntimeError("cannot turn %s into a number" % (_zquote(x) if isinstance(x, str) else _zkind(x)))
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x.strip())
        except ValueError:
            pass
    raise ZoomyRuntimeError("cannot turn %s into a number" % (_zquote(x) if isinstance(x, str) else _zkind(x)))


def _zformat(x, n):
    return "%.*f" % (int(n), float(x))


def _zkind(x):
    if x is None:
        return "nothing"
    if isinstance(x, bool):
        return "a yes/no value"
    if isinstance(x, (int, float, _BD)):
        return "a number"
    if isinstance(x, str):
        return "text"
    if isinstance(x, (list, tuple)):
        return "a list"
    if isinstance(x, dict):
        return "a table"
    return "a " + type(x).__name__


# ---------------------------------------------------------------------------- lists, tables, text
def _zix(seq, i):
    if isinstance(seq, dict):
        try:
            return seq[i]
        except KeyError:
            raise ZoomyRuntimeError("the table has no entry %s" % _zshow(i, True))
        except TypeError:
            raise ZoomyRuntimeError("cannot use %s as a table key" % _zkind(i))
    if isinstance(seq, (list, tuple, str)):
        k = _zint64(i)
        if not 0 <= k < len(seq):
            raise ZoomyRuntimeError("array index out of range")
        return seq[k]
    if isinstance(i, float) and i == _zmath.floor(i):
        i = int(i)
    try:
        return seq[i]
    except (IndexError, KeyError):
        raise ZoomyRuntimeError("array index out of range")


def _zset(seq, i, v):
    if isinstance(seq, dict):
        seq[i] = v
        return
    if isinstance(seq, list):
        k = _zint64(i)
        if not 0 <= k < len(seq):
            raise ZoomyRuntimeError("array index out of range")
        seq[k] = v
        return
    if isinstance(i, float) and i == _zmath.floor(i):
        i = int(i)
    try:
        seq[i] = v
    except (IndexError, KeyError):
        raise ZoomyRuntimeError("array index out of range")
    except TypeError as e:
        raise ZoomyRuntimeError("cannot change items of %s" % _zkind(seq))


def _zattr(obj, name):                                     # the player's score: a table entry, or a Python attribute
    if isinstance(obj, dict):
        try:
            return obj[name]
        except KeyError:
            raise ZoomyRuntimeError("the table has no entry %s" % _zshow(name, True))
    return getattr(obj, name)


def _zsetattr(obj, name, value):
    if isinstance(obj, dict):
        obj[name] = value
    else:
        setattr(obj, name, value)


def _zlen(x):
    try:
        return len(x)
    except TypeError:
        raise ZoomyRuntimeError("%s has no length" % _zkind(x))


def _zcontains(a, b):
    try:
        return b in a
    except TypeError:
        raise ZoomyRuntimeError("cannot look inside %s" % _zkind(a))


def _zempty(x):
    return x is None or (hasattr(x, "__len__") and len(x) == 0)


def _zstarts(a, b):
    return a.startswith(b)


def _zends(a, b):
    return a.endswith(b)


def _ziter(x):
    if isinstance(x, (list, tuple, str)):
        return list(x) if isinstance(x, list) else x
    if isinstance(x, (int, float)):
        raise ZoomyRuntimeError("cannot go through each item of %s" % _zkind(x))
    return x


def _zsum(x):
    return sum(x, 0.0)


def _zextreme(fn, x):
    if len(x) == 0:
        raise ZoomyRuntimeError("the list is empty")
    return fn(x)


def _zreversed(x):
    return x[::-1] if isinstance(x, str) else list(reversed(x))


def _zlast(x):
    if len(x) == 0:
        raise ZoomyRuntimeError("the list is empty")
    return x[-1]


def _zjoin(items, sep):
    return sep.join(_zshow(i) for i in items)


def _zsplit(text, sep):
    return list(text) if sep == "" else text.split(sep)


def _zslice(x, a, b):
    return x[max(_zint64(a), 0):max(_zint64(b), 0)]


def _zpos(x, seq):
    try:
        return float(seq.index(x))
    except ValueError:
        return -1.0


def _zinsert(seq, i, v):
    k = _zint64(i)
    if not 0 <= k <= len(seq):
        raise ZoomyRuntimeError("array index out of range")
    seq.insert(k, v)


def _zremove(c, v):
    if isinstance(c, dict):
        if v not in c:
            raise ZoomyRuntimeError("the table has no entry %s" % _zshow(v, True))
        del c[v]
        return
    try:
        c.remove(v)
    except ValueError:
        raise ZoomyRuntimeError("%s is not in the list" % _zshow(v, True))


def _zremove_at(c, i):
    if isinstance(c, dict):
        _zremove(c, i)
        return
    k = _zint64(i)
    if not 0 <= k < len(c):
        raise ZoomyRuntimeError("array index out of range")
    del c[k]


def _zsort(seq, descending=False):
    try:
        seq.sort(reverse=descending)
    except TypeError:
        raise ZoomyRuntimeError("cannot sort a list that mixes numbers and text")


def _zsorted(seq):
    try:
        return sorted(seq)
    except TypeError:
        raise ZoomyRuntimeError("cannot sort a list that mixes numbers and text")


def _zlines(t):
    return t.splitlines()


def _zrandbetween(a, b):
    if float(a) == int(a) and float(b) == int(b):
        return float(_zrandom.randint(int(a), int(b)))
    return _zrandom.uniform(a, b)


def _zcode(c):
    if not isinstance(c, str) or len(c) != 1:
        raise ZoomyRuntimeError("expected a single character")
    return float(ord(c))


def _zchar_to_num(c):
    """'0'..'9' -> 0..9 and ok=1; anything else -> NaN and ok=0 (c may be a character code or a 1-letter text)."""
    if isinstance(c, str):
        c = ord(c) if len(c) == 1 else -1
    c = _zint64(c)
    if 48 <= c <= 57:
        return float(c - 48), 1.0
    return _NAN, 0.0


def _zchar(n):
    return chr(_zint64(n))


# ---------------------------------------------------------------------------- calling Python
def _zpy(fn, *args, **kwargs):
    """Call a Python function: numbers that are whole are handed over as ints (range(5), zeros(3), ...)."""
    def whole(a):
        if isinstance(a, list):                        # lists are converted in place so Python can also change them
            for i, x in enumerate(a):
                a[i] = whole(x)
            return a
        if isinstance(a, dict):
            for k in list(a):
                a[k] = whole(a[k])
            return a
        return int(a) if isinstance(a, float) and a == a and abs(a) < 1e15 and a == int(a) else a
    return fn(*[whole(a) for a in args], **{k: whole(v) for k, v in kwargs.items()})


# ---------------------------------------------------------------------------- input
class _ZIn:
    pb = -1
    f = None                      # an open input file (open the file "x" for reading); None = standard input


_zin = _ZIn()


def _zgetc():
    if _zin.pb != -1:
        c, _zin.pb = _zin.pb, -1
        return c
    _zflush()
    b = (_zin.f or _zsys.stdin.buffer).read(1)
    return b[0] if b else -1


def _zcores():
    import os
    try:
        n = len(os.sched_getaffinity(0))
    except Exception:
        n = os.cpu_count() or 1
    return max(1, n) if _ZINTS else float(max(1, n))


def _zclock():
    import time
    ms = time.monotonic_ns() // 1000000
    return ms if _ZINTS else float(ms)


def _zopen(path):
    _zclose()
    try:
        _zin.f = open(path, "rb")
    except OSError:
        return 0 if _ZINTS else 0.0
    _zin.pb = -1
    return 1 if _ZINTS else 1.0


def _zsyscall(num, *args):
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    r = libc.syscall(ctypes.c_long(int(num)), *[ctypes.c_long(int(a)) for a in args])
    return -ctypes.get_errno() if r == -1 else int(r)


def _zopenarr(arr):
    name = []
    for c in arr:
        c = int(c)
        if c == 0:
            break
        name.append(chr(c))
    return _zopen("".join(name))


def _zfsize():
    if _zin.f is None:
        return -1 if _ZINTS else -1.0
    try:
        n = _zos.fstat(_zin.f.fileno()).st_size
    except OSError:
        n = -1
    _zin.pb = -1
    return n if _ZINTS else float(n)


def _zseek(pos):
    if _zin.f is not None:
        try:
            _zin.f.seek(int(pos))
        except (OSError, ValueError):
            pass
    _zin.pb = -1


def _zclose():
    if _zin.f is not None:
        _zin.f.close()
        _zin.f = None
    _zin.pb = -1


def _zws(c):
    return c == 32 or 9 <= c <= 13


def _zread_num():
    while True:
        c = _zgetc()
        if c == -1:
            return 0.0, 0.0
        if not _zws(c):
            break
    neg = False
    if c == 45:
        neg, c = True, _zgetc()
    elif c == 43:
        c = _zgetc()
    m, digits, frac, dot = 0.0, 0, 0, False
    while c != -1:
        if 48 <= c <= 57:
            m = m * 10.0 + float(c - 48)
            digits += 1
            if dot:
                frac += 1
            c = _zgetc()
        elif c == 46 and not dot:
            dot = True
            c = _zgetc()
        else:
            _zin.pb = c
            break
    if digits == 0:
        _zin.pb = -1
        return 0.0, 0.0
    p = 1.0
    for _ in range(frac):
        p *= 10.0
    m = m / p
    return (-m if neg else m), 1.0


def _zread_char():
    while True:
        c = _zgetc()
        if c == -1:
            return (0, 0) if _ZINTS else (0.0, 0.0)
        if not _zws(c):
            return (c, 1) if _ZINTS else (float(c), 1.0)


def _zread_byte():
    c = _zgetc()
    if c == -1:
        return (0, 0) if _ZINTS else (0.0, 0.0)
    return (c, 1) if _ZINTS else (float(c), 1.0)


def _zread_line():
    c = _zgetc()
    if c == -1:
        return "", 0.0
    buf = bytearray()
    while c not in (-1, 10):
        buf.append(c)
        c = _zgetc()
    if buf.endswith(b"\r"):
        del buf[-1]
    return buf.decode("utf-8", "replace"), 1.0


def _zask(prompt):
    _zw(_zshow(prompt))
    _zflush()
    text, ok = _zread_line()
    globals()["z_input_ok"] = ok
    return text


def _zargs():
    return list(_zsys.argv[1:])


# ---------------------------------------------------------------------------- files
def _zreadfile(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        raise ZoomyRuntimeError("cannot read file %s (%s)" % (_zquote(str(path)), e.strerror))


def _zwritefile(path, text, mode):
    try:
        with open(path, mode, encoding="utf-8") as f:
            f.write(_zshow(text))
    except OSError as e:
        raise ZoomyRuntimeError("cannot write file %s (%s)" % (_zquote(str(path)), e.strerror))


def _zdeletefile(path):
    try:
        _zos.remove(path)
    except OSError as e:
        raise ZoomyRuntimeError("cannot delete file %s (%s)" % (_zquote(str(path)), e.strerror))


# ---------------------------------------------------------------------------- errors
_ZTYPES = {"float": "a number", "int": "a number", "str": "text", "list": "a list", "dict": "a table",
           "NoneType": "nothing", "bool": "a yes/no value", "tuple": "a list"}
_ZOPS = {"+": "plus", "-": "minus", "*": "times", "/": "divided by", "%": "mod", "**": "to the power of"}


def _znice(e):
    import re
    if isinstance(e, (ZoomyRuntimeError, ZoomyFailure)):
        return str(e)
    msg = str(e)
    if isinstance(e, (UnboundLocalError, NameError)):
        m = re.search(r"'(?:z_)?(\w+)'", msg)
        return "the variable '%s' has no value yet" % (m.group(1) if m else "?")
    if isinstance(e, ModuleNotFoundError):
        return "the python library '%s' is not installed (try: pip install %s)" % (e.name, (e.name or "").split(".")[0])
    if isinstance(e, ImportError):
        return "cannot use that python library: " + msg
    if isinstance(e, KeyboardInterrupt):
        return "stopped"
    if isinstance(e, RecursionError):
        return "too many nested calls (a function calls itself without stopping?)"
    m = re.match(r"unsupported operand type\(s\) for ([^:]+): '(\w+)' and '(\w+)'", msg)
    if m:
        return "cannot use '%s' with %s and %s" % (_ZOPS.get(m.group(1).strip(), m.group(1)),
                                                   _ZTYPES.get(m.group(2), m.group(2)), _ZTYPES.get(m.group(3), m.group(3)))
    m = re.match(r'can only concatenate (\w+) \(not "(\w+)"\) to (\w+)', msg)
    if m:
        return "cannot add %s to %s (use 'text of ...' or {...} to put a number into text)" % (
            _ZTYPES.get(m.group(2), m.group(2)), _ZTYPES.get(m.group(3), m.group(3)))
    m = re.match(r"'([<>]=?)' not supported between instances of '(\w+)' and '(\w+)'", msg)
    if m:
        return "cannot compare %s with %s" % (_ZTYPES.get(m.group(2), m.group(2)), _ZTYPES.get(m.group(3), m.group(3)))
    m = re.match(r"bad operand type for unary -: '(\w+)'", msg)
    if m:
        return "cannot negate " + _ZTYPES.get(m.group(1), m.group(1))
    m = re.match(r"'(\w+)' object has no attribute '(\w+)'", msg)
    if m:
        return "%s has nothing called '%s'" % (_ZTYPES.get(m.group(1), "a " + m.group(1)), m.group(2))
    m = re.match(r"'(\w+)' object is not callable", msg)
    if m:
        return "%s cannot be called like a function" % _ZTYPES.get(m.group(1), "a " + m.group(1))
    msg = re.sub(r"\bz_(\w+)", r"\1", msg)
    if isinstance(e, TypeError):
        return msg
    return "%s: %s" % (type(e).__name__, msg) if msg else type(e).__name__


def _zwarn(msg):
    _zsys.stdout.flush()
    _zsys.stderr.write("zoomy: warning: " + str(msg) + "\n")
    _zsys.stderr.flush()


def _zdie(e, g, zlines, name):
    if isinstance(e, SystemExit):
        raise e
    if isinstance(e, BrokenPipeError):                     # e.g. piped into `head`
        try:
            _zos.dup2(_zos.open(_zos.devnull, _zos.O_WRONLY), 1)
        except Exception:
            pass
        raise SystemExit(0)
    _zflush()
    if isinstance(e, KeyboardInterrupt):
        raise SystemExit(130)
    line = None
    tb = e.__traceback__
    while tb is not None:
        if tb.tb_frame.f_globals is g and tb.tb_lineno in zlines:
            line = zlines[tb.tb_lineno]
        tb = tb.tb_next
    where = " (%s, line %d)" % (name, line) if line else ""
    if isinstance(e, ZoomyFailure):
        _zsys.stderr.write("zoomy: error: %s%s\n" % (e, where))
        raise SystemExit(1)
    _zsys.stderr.write("zoomy: runtime error: %s%s\n" % (_znice(e), where))
    if _zos.environ.get("ZOOMY_DEBUG"):
        import traceback
        traceback.print_exception(type(e), e, e.__traceback__)
    raise SystemExit(255)
