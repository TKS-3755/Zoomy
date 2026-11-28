"""Zoomy 7: built-in constants.  A name here is read like a variable that nobody can change; a program that makes a variable of the
same name (Let a number be called c) simply uses its own.  The mathematical constants are kept to 100 decimals (cut, not rounded);
a Zoomy number is a 64-bit float, so a program sees the nearest float.  In integer mode a constant is cut to a whole number
(pi is 3, the speed of light is 299792458) and one that does not fit in 64 bits is an error.  The physical constants are the SI / CODATA values."""

# canonical name -> (value as text, what it is)
CONSTANTS = {
    "pi": ("3.1415926535897932384626433832795028841971693993751058209749445923078164062862089986280348253421170679821480865132823066470938446095505822317253594081284811174502841027019385211055596446229489549303819644288109756659334461284756482337867831652712019091456485669234603486104543266482133936072602491412737245870066063155881748815209209628292540", "the ratio of a circle's circumference to its diameter"),
    "e": ("2.7182818284590452353602874713526624977572470936999595749669676277240766303535475945713821785251664274", "Euler's number, the base of natural logarithms"),
    "tau": ("6.2831853071795864769252867665590057683943387987502116419498891846156328125724179972560696506842341359", "2 pi, one full turn in radians"),
    "sqrt2": ("1.4142135623730950488016887242096980785696718753769480731766797379907324784621070388503875343276415727", "the square root of 2"),
    "sqrt3": ("1.7320508075688772935274463415058723669428052538103806280558069794519330169088000370811461867572485756", "the square root of 3"),
    "sqrt5": ("2.2360679774997896964091736687312762354406183596115257242708972454105209256378048994144144083787822749", "the square root of 5"),
    "golden_ratio": ("1.6180339887498948482045868343656381177203091798057628621354486227052604628189024497072072041893911374", "(1 + sqrt 5) / 2"),
    "ln2": ("0.6931471805599453094172321214581765680755001343602552541206800094933936219696947156058633269964186875420014810205706857336855202357581305570326707516350759619307275708283714351903070386238916734711233501153644979552391204751726815749320651555247341395258829504530070953263666426541042391578149520437404303855008019441706416715186447128399681", "the natural logarithm of 2"),
    "ln10": ("2.3025850929940456840179914546843642076011014886287729760333279009675726096773524802359972050895982983", "the natural logarithm of 10"),
    "euler_gamma": ("0.5772156649015328606065120900824024310421593359399235988057672348848677267776646709369470632917467495", "the Euler-Mascheroni constant"),
    "catalan": ("0.9159655941772190150546035149323841107741493742816721342664981196217630197762547694793565129261151062", "Catalan's constant"),
    "speed_of_light": ("299792458", "metres per second (exact)"),
    "gravitational_constant": ("6.67430e-11", "G, in m^3 kg^-1 s^-2 (CODATA 2018)"),
    "planck_constant": ("6.62607015e-34", "h, in joule seconds (exact)"),
    "reduced_planck_constant": ("1.054571817646156e-34", "hbar = h / 2 pi, in joule seconds"),
    "standard_gravity": ("9.80665", "g, metres per second squared (exact)"),
    "boltzmann_constant": ("1.380649e-23", "joules per kelvin (exact)"),
    "avogadro_constant": ("6.02214076e23", "per mole (exact)"),
    "elementary_charge": ("1.602176634e-19", "coulombs (exact)"),
    "gas_constant": ("8.31446261815324", "joules per mole kelvin (exact)"),
    "stefan_boltzmann_constant": ("5.670374419184429e-8", "watts per square metre kelvin^4"),
    "vacuum_permittivity": ("8.8541878188e-12", "farads per metre (CODATA 2022)"),
    "vacuum_permeability": ("1.25663706127e-6", "newtons per ampere squared (CODATA 2022)"),
    "fine_structure_constant": ("7.2973525643e-3", "no unit (CODATA 2022)"),
    "electron_mass": ("9.1093837139e-31", "kilograms (CODATA 2022)"),
    "proton_mass": ("1.67262192595e-27", "kilograms (CODATA 2022)"),
    "neutron_mass": ("1.67492750056e-27", "kilograms (CODATA 2022)"),
    "atomic_mass_unit": ("1.66053906892e-27", "kilograms (CODATA 2022)"),
    "earth_mass": ("5.9722e24", "kilograms"),
    "earth_radius": ("6371000", "metres (mean radius)"),
    "solar_mass": ("1.98841e30", "kilograms"),
    "astronomical_unit": ("149597870700", "metres (exact)"),
    "light_year": ("9460730472580800", "metres (exact)"),
    "parsec": ("3.0856775814913673e16", "metres"),
}

# short names for the best known ones
ALIASES = {"phi": "golden_ratio", "G": "gravitational_constant", "g": "standard_gravity", "c": "speed_of_light",
           "h": "planck_constant", "hbar": "reduced_planck_constant"}

NAMES = {**{k: k for k in CONSTANTS}, **ALIASES}          # every name a program can use -> its canonical name


def py_name(name):
    """the name the front end gives the built-in variable (no user name starts with two underscores)"""
    return "__" + NAMES[name]


PY_NAMES = {"__" + k: k for k in CONSTANTS}


def value(py):
    return float(CONSTANTS[PY_NAMES[py]][0])


def text(py):
    """the constant exactly as written in the table (all its digits)"""
    return CONSTANTS[PY_NAMES[py]][0]


def whole(py):
    """the constant as a whole number (cut toward zero), or None when it does not fit in 64 bits"""
    n = int(float(CONSTANTS[PY_NAMES[py]][0]))
    return n if -(1 << 63) <= n < (1 << 63) else None
