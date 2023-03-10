#!/bin/py

#
#
# Simple, customizable C/C++ build system in Python.
# By Orbyfied, 2023
#
#

from json import JSONDecoder
import os
import subprocess
import shutil
from sys import argv

################################
# Utilities
################################

class Reader:
    def __init__(self, str):
        self.str = str
        self.idx = 0

    def current(self):
        if self.idx < 0 or self.idx >= len(self.str):
            return None
        return self.str[self.idx]

    def next(self, amt = 1):
        self.idx += amt
        if self.idx < 0 or self.idx >= len(self.str):
            return None
        return self.str[self.idx]

    def prev(self, amt = 1):
        self.idx -= amt
        if self.idx < 0 or self.idx >= len(self.str):
            return None
        return self.str[self.idx]

    def peek(self, off):
        idx = self.idx + off
        if idx >= len(self.str) or idx < 0:
            return None
        return self.str[idx]

    def at(self, index):
        if index > 0:
            return self.str[index]
        else:
            idx = self.idx - abs(index)
            if idx >= len(self.str) or idx < 0:
                return None
            return self.str[idx]

    def collect(self, pred: function):
        str = ""
        while self.current() != None and pred(self.current()):
            str += self.current()
        return str

    def pcollect(self, pred: function):
        while self.current() != None and pred(self.current()):
            pass
        return str

def is_path_sep(char):
    return char == '\\' or char == '/'

def fix_path(pstr):
    seg      = ""
    segments = []
    reader = Reader(pstr)
    char   = reader.current()
    while char != None:
        # check for separator
        if is_path_sep(char):
            if len(seg) > 2 and seg[0] == '%':
                seg = os.getenv(seg[1:-1])
            segments.append(seg)
            seg = ""
        else:
            seg += char

        char = reader.next()

    # stitch to string
    result = ""
    for segment in segments:
        result += segment + "/"
    return result

# get index by position/offset
# into a list of length len
def get_idx_by_pos(len, pos):
    if pos < 0:
        return len + pos
    else:
        return pos

################################
# CLI
################################

# the pos value to signal the argument
# should be appended to the end
POS_APPEND_BACK = 0xFFFFFFFF

class ArgError(RuntimeError):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)

# simple arg repr
class Arg:
    # create a simple named arg
    def new(name: str, char: str, ty: type):
        return Arg(name, char, ty, None, None)
    # create a simple positional arg
    def new_positional(name: str, ty: type):
        return Arg(name, None, ty, None, POS_APPEND_BACK)
    # create a positional arg at the specified idx/pos
    def new_positional_at(name: str, ty: type, pos: int):
        return Arg(name, None, ty, None, pos)
    # create a switch arg
    def new_switch(name: str, char: str, ty: type, switch_handler: function):
        return Arg(name, char, ty, switch_handler, None)

    def __init__(self, name: str, char: str, ty: type, sw_handler: function, pos: int):
        self.name       = name
        self.char       = char
        self.ty         = ty
        self.sw_handler = sw_handler
        self.pos        = pos

# a parser for a type
class ArgParser: pass
class TypeParser:
    def __init__(self, ty: type, pfunc: function):
        self.ty = ty
        self.pfunc = pfunc

    # abstract: parses the type
    def parse(self, parser: ArgParser, arg: Arg, reader: Reader):
        return self.pfunc(parser, arg, reader)

# arg parser
class ArgParser:
    def __init__(self):
        self.arg_map  = { } # args by name
        self.pos_args = [ ] # positioned list of args
        self.by_char  = { } # args by char
        self.types    = { } # type parsers

    def define_type(self, ty: TypeParser):
        self.types[ty.ty] = ty

    def add(self, arg: Arg):
        self.arg_map[arg.name] = arg
        if arg.char != None:
            self.by_char[arg.char] = arg
        if arg.pos != None:
            if arg.pos == POS_APPEND_BACK:
                self.pos_args.append(arg)
            else:
                self.pos_args.insert(get_idx_by_pos(len(self.pos_args), arg.pos), arg)

    def parse_val(self, arg: Arg, reader: Reader):
        try:
            return arg.ty.parse(self, arg, reader)
        except ArgError as e:
            print("arg: error occured parsing " + arg.name + ": " + e)
            raise ArgError("arg parse failed")

    def parse(self, str: str, out: dict):
        if not out:
            out = { }

        pIdx = 0 # positional arg index
        reader = Reader(str) # string reader
        c = None # char

        while reader.current() != None:
            # collect whitespace
            reader.pcollect(lambda c : c.isspace())

            c = reader.current()

            # check for flags
            if c == '-':
                # check for named
                if reader.next() == '-':
                    # collect name
                    reader.next()
                    name = reader.collect(lambda c : c != ' ' and c != '=')

                    arg = self.arg_map[name]
                    if not arg:
                        raise ArgError("unknown arg by name " + name)

                    # check for explicit value
                    # or spaced value
                    # otherwise handle switch
                    val = None
                    if not arg.sw_handler or reader.current() == '=':
                        reader.next()
                        val = self.parse_val(arg, reader)
                    else: # switch
                        val = arg.sw_handler(self, arg)

                    # put val
                    out[arg.name] = val
                else:
                    while reader.current() != None and reader.current() != ' ':
                        arg = self.arg_map[reader.current()]
                        if not arg:
                            raise ArgError("unknown arg by char '" + reader.current() + "'")

                        # check switch
                        if not arg.sw_handler:
                            reader.next()
                            val = self.parse_val(arg, reader)
                            out[arg.name] = val
                            break
                        else:
                            out[arg.name] = arg.sw_handler(self, arg)
                            reader.next()
            else:
                # handle positional arg
                arg = self.pos_args[pIdx]
                pIdx += 1
                val = self.parse_val(arg, reader)
                out[arg.name] = val

        return out

################################
# State
################################

DEBUG = False

class BuildTarget:
    def __init__(self, name : str, type : str, src_dir : str):
        self.name = name
        self.type = type
        self.src_dir = src_dir

class BuildState:
    def __init__(self):
        self.include_dirs = []
        self.lib_dirs     = []
        self.dependencies = []
        pass

    def prepare(self):
        if not os.path.exists(self.obj_dir):
            os.makedirs(self.obj_dir)
        if not os.path.exists(self.bin_dir):
            os.makedirs(self.bin_dir)

    def clean(self):
        shutil.rmtree(self.obj_dir)
        shutil.rmtree(self.bin_dir)

    def set_target(self, target):
        self.target = target
        return self

    def set_obj_dir(self, fn):
        self.obj_dir = fn
        return self

    def set_bin_dir(self, fn):
        self.bin_dir = fn
        return self

    def set_include_dirs(self, dirs):
        self.include_dirs = dirs
        return self

    def set_dependencies(self, deps):
        self.dependencies = deps
        return self

    def add_include_dir(self, fn):
        self.include_dirs.append(fn)
        return self

    def add_lib_dir(self, fn):
        self.lib_dirs.append(fn)
        return self

    def add_lib_file_dependency(self, fn):
        self.dependencies.append("lib_file://" + fn)

    def add_project_dir_dependency(self, fn):
        self.dependencies.append("project_dir://" + fn);

def get_platform_str(osName, arch):
    return arch + ("-" + osName if osName != None else "")

################################
# Compilation
################################

CXX_COMPILER = 'g++'
CXX_CFLAGS   = '-shared'

def get_obj_dir(state, target, osName, arch):
    # construct name
    name = os.path.join(state.obj_dir, target.name + "-" + get_platform_str(osName, arch))
    # create if absent
    if not os.path.exists(name):
        os.makedirs(name)
    # return
    return name;

def get_obj_output(state : BuildState, target, rel_filename, osName, arch):
    # replace directory seperators
    rel_filename = rel_filename.replace("/",  "+")
    rel_filename = rel_filename.replace("\\", "+")
    # split text and add .o extension
    fn = os.path.splitext(rel_filename)[0] + ".o";
    # join with object directory
    return os.path.join(get_obj_dir(state, target, osName, arch), fn)

def compile_file(state : BuildState, target, filename, osName, arch):
    # build flags
    flags = []
    # append source file
    flags.append("-c \"" + filename + "\"")
    # append object output
    obj_out = get_obj_output(state, target, filename, osName, arch)
    flags.append("-o \"" + obj_out + "\"")
    # append architecture
    if arch == 'x64':
        flags.append("-m64")
    elif arch == 'x32':
        flags.append("-m32")
    # append platform defines
    if osName != None:
        flags.append("-D_OS=" + osName)
    flags.append("-D_ARCH=" + arch)
    # append include directories
    for include_dir in state.include_dirs:
        flags.append("-I \"" + include_dir + "\"")
    # append user defined flags
    flags.append(CXX_CFLAGS)
    # stringify flags
    flagStr = ""
    for flag in flags:
        flagStr = flagStr + flag + " "
    # construct command
    cmd = CXX_COMPILER + " " + flagStr

    # call command
    print("Compiling '" + filename + "' " + target.name + " (" + target.type + ") " + get_platform_str(osName, arch))
    if DEBUG: print("-> '" + cmd + "'")
    process = subprocess.Popen(cmd, shell=True)
    process.wait()

    # return code
    return process.returncode, cmd, filename, obj_out

################################
# Linking
################################

LD_EXE   = 'g++'
LD_FLAGS = '-shared'

def get_output_file_name(state : BuildState, target : BuildTarget, osName : str, arch):
    # get file extension
    ext = ""
    if target.type == 'executable':
        if osName.lower().find('win') != -1:
            ext = '.exe'
        else:
            ext = ''
    elif target.type.startswith('lib'):
        spl  = target.type.split(':')
        if len(spl) < 2:
            raise ValueError('Invalid target type: %s' % target) 
        spec = spl[1]
        if spec == 'static':
            if osName.lower().find('linux') != -1:
                ext = '.a'
            else:
                ext = '.lib'
        elif spec == 'dynamic':
            if osName.lower().find('win') != -1:
                ext = '.dll'
            elif osName.lower().find('linux') != -1:
                ext = '.so'
            else:
                ext = '.dylib'
    # build final file name
    return target.name + "-" + get_platform_str(osName, arch) + ext

def link_target(state, target, osName, arch):
    # get obj file directory
    obj_dir = get_obj_dir(state, target, osName, arch)

    # build flags
    flags = []
    # append output file
    if not os.path.exists(state.bin_dir):
        os.makedirs(state.bin_dir)
    out_file = os.path.join(state.bin_dir, get_output_file_name(state, target, osName, arch))
    flags.append("-o \"" + out_file + "\"")
    # append all object files
    for of in os.listdir(obj_dir):
        if of.endswith(".o"):
            flags.append("\"" + os.path.join(obj_dir, of) + "\"")
    # append architecture
    if arch == 'x64':
        flags.append("-m64")
    elif arch == 'x32':
        flags.append("-m32")
    # TODO: append dependencies
    # append user flags
    flags.append(LD_FLAGS)
    # stringify flags
    flagStr = ""
    for flag in flags:
        flagStr = flagStr + flag + " "
    # construct command
    cmd = LD_EXE + " " + flagStr

    # call command
    print("Linking " + target.name + " (" + target.type + ") " + get_platform_str(osName, arch) + " -> " + out_file)
    if DEBUG: print("-> '" + cmd + "'")
    process = subprocess.Popen(cmd, shell=True)
    process.wait()

    # return exit
    return process.returncode, cmd, out_file

################################
# Build
################################

OS_LIST   = [ 'win', 'linux', 'mac' ]
ARCH_LIST = [ 'x64', 'x86' ]

SRC_FILE_EXTENSIONS = [ 'c', 'cpp', 'cxx', 'cx', 'c++' ]

def compile_all_in(state : BuildState, src_dir : str, osName, arch):
    # for all files in the directory
    for src_file in os.listdir(src_dir):
        if os.path.isdir(src_file):
            # compile all files in that directory
            compile_all_in(state, src_file, osName, arch)
        else:
            spl = src_file.split('.')
            if len(spl) > 1 and spl[1] in SRC_FILE_EXTENSIONS:
                # compile file
                code, cmd, _, ofn = compile_file(state, state.target, src_file, osName, arch)
                if code != 0:
                    print("Compiling " + src_file + " (" + get_platform_str(osName, arch) + ") failed with code " + str(code))
                    return -1
    return 0

def build_all_for(state : BuildState, osName, arch):
    # print
    target = state.target
    print("Building target " + target.name + " (" + target.type + ") for platform " + get_platform_str(osName, arch))

    # compile all files
    code = compile_all_in(state, target.src_dir, osName, arch)
    if code != 0:
        print("Compiling " + target.name + " (" + target.type + ") failed for platform " + get_platform_str(osName, arch))
        return
    else:
        print("Compiled " + target.name + " (" + target.type + ") for platform " + get_platform_str(osName, arch))
    # link all files
    code, ldcmd, binfn = link_target(state, target, osName, arch)
    if code != 0:
        print("Linking " + target.name + " (" + target.type + ") failed for platform " + get_platform_str(osName, arch))
        return
    else:
        print("Linked " + target.name + " (" + target.type + ") for platform " + get_platform_str(osName, arch))

    # complete
    print("Build of " + target.name + " (" + target.type + ") complete for platform " + get_platform_str(osName, arch))

def build_all(state : BuildState, target : BuildTarget, osNames, archs):
    # set target to build
    state.set_target(target)
    print("Building target " + target.name + " (" + target.type + ") for all platforms")

    # for all platforms build
    for arch in archs:
        for osName in osNames:
            build_all_for(state, osName, arch)

################################
# Main
################################

def main_build_json(mdir, jsonfile):
    # print
    print("Loading module from '" + jsonfile + "' in '" + mdir + "'")

    # read json from file
    filestr = open(jsonfile, 'r')
    jsonstr = filestr.read()
    filestr.close()
    json = JSONDecoder().decode(jsonstr)

    # get properties from json
    pTarget = json["target"]
    pTSrcDir = os.path.join(mdir, fix_path(pTarget["src_dir"]))
    pTName   = pTarget["name"]
    pTType   = pTarget["type"]
    iTarget = BuildTarget(pTName, pTType, pTSrcDir)

    pArchs    = json["architectures"]
    pOses     = json["os_names"]
    pObjDir   = fix_path(json["obj_dir"])
    pBinDir   = fix_path(json["bin_dir"])
    pInclDirs = json["include_dirs"]
    pDeps     = json["dependencies"]

    rInclDirs = []
    for d in pInclDirs:
        rInclDirs.append(fix_path(d))
    rDeps = []
    for d in pDeps:
        rDeps.append(fix_path(d))

    iState = BuildState()
    iState.set_bin_dir(pBinDir)
    iState.set_obj_dir(pObjDir)
    iState.set_include_dirs(rInclDirs)
    iState.set_dependencies(rDeps)
    iState.set_target(iTarget)

    # call build
    build_all(iState, iTarget, pOses, pArchs)

def main(args):
    main_build_json(".", "module.json")

if __name__ == '__main__':
    main(argv)