import sys
from setuptools import setup, Extension

define_macros = []
if sys.platform == "win32":
    define_macros.append(("WIN32", "1"))

setup(
    name="chm-docs",
    ext_modules=[
        Extension(
            "_chmlib",
            sources=[
                "_chmlib.c",
                "vendor/chmlib/chm_lib.c",
                "vendor/chmlib/lzx.c",
            ],
            include_dirs=["vendor/chmlib"],
            define_macros=define_macros,
        )
    ],
)
