"""Run the shipped script in Plymouth's interpreter with display-free test doubles.

Uses exported script.so functions from upstream script{,-parse,-execute,-object}.h.
It never starts plymouthd or loads its sprite, image, renderer or console libraries.
"""
import ctypes as C
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'bromigos' / 'bromigos.script'
LIBRARY = Path('/usr/lib/plymouth/script.so')


class State(C.Structure):
    _fields_ = [('user_data', C.c_void_p), ('global_', C.c_void_p),
                ('local', C.c_void_p), ('this', C.c_void_p)]


class Result(C.Structure):
    _fields_ = [('type', C.c_int), ('object', C.c_void_p)]


class Theme:
    def __init__(self, mode='boot', width=1280, height=720):
        self.lib = C.CDLL(str(LIBRARY))
        signatures = {
            'script_state_new': ([C.c_void_p], C.POINTER(State)),
            'script_state_destroy': ([C.POINTER(State)], None),
            'script_parse_string': ([C.c_char_p, C.c_char_p], C.c_void_p),
            'script_parse_op_free': ([C.c_void_p], None),
            'script_execute': ([C.POINTER(State), C.c_void_p], Result),
            'script_obj_unref': ([C.c_void_p], None),
            'script_obj_is_null': ([C.c_void_p], C.c_bool),
            'script_obj_hash_get_element': ([C.c_void_p, C.c_char_p], C.c_void_p),
            'script_obj_hash_get_number': ([C.c_void_p, C.c_char_p], C.c_double),
            'script_obj_hash_get_string': ([C.c_void_p, C.c_char_p], C.c_void_p),
            'script_lib_math_setup': ([C.POINTER(State)], C.c_void_p),
            'script_lib_math_destroy': ([C.c_void_p], None),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes = args
            function.restype = result
        self.libc = C.CDLL(None)
        self.libc.free.argtypes = [C.c_void_p]
        self.state = self.lib.script_state_new(None)
        self.math = self.lib.script_lib_math_setup(self.state)
        self.ops = []
        self.run(f'test_mode = {json.dumps(mode)}; test_width = {width}; test_height = {height};')
        self.run((HERE / 'fake.script').read_text())
        self.run(SCRIPT.read_text())

    def run(self, source):
        op = self.lib.script_parse_string(source.encode(), b'offscreen-test')
        if not op:
            raise AssertionError('Plymouth rejected script syntax')
        self.ops.append(op)  # functions reference their parsed bodies until close
        result = self.lib.script_execute(self.state, op)
        if result.object:
            self.lib.script_obj_unref(result.object)
        if result.type not in (0, 1):
            raise AssertionError(f'Plymouth script execution failed: {result.type}')

    def get(self, path, text=False):
        parts = path.split('.')
        obj = self.state.contents.global_
        owned = []
        try:
            for part in parts[:-1]:
                obj = self.lib.script_obj_hash_get_element(obj, part.encode())
                owned.append(obj)
            if not text:
                return self.lib.script_obj_hash_get_number(obj, parts[-1].encode())
            value = self.lib.script_obj_hash_get_element(obj, parts[-1].encode())
            owned.append(value)
            if self.lib.script_obj_is_null(value):
                return None
            pointer = self.lib.script_obj_hash_get_string(obj, parts[-1].encode())
            if not pointer:
                return None
            try:
                return C.string_at(pointer).decode()
            finally:
                self.libc.free(pointer)
        finally:
            for item in reversed(owned):
                self.lib.script_obj_unref(item)

    def close(self):
        self.lib.script_state_destroy(self.state)
        for op in reversed(self.ops):
            self.lib.script_parse_op_free(op)
        self.lib.script_lib_math_destroy(self.math)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
