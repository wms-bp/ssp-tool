from setuptools import setup, Extension

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
        )
    ],
)
