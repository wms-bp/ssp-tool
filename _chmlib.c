/*
 * _chmlib.c - Python C extension wrapping CHMLib
 *
 * Based on pychm (https://github.com/dottedmag/pychm), simplified for
 * chm-docs: only open/close/enumerate/resolve/retrieve are needed.
 *
 * Vendored CHMLib source is included directly — no system libchm required.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "chm_lib.h"

#define CHMFILE_CAPSULE_NAME "C.chmFile"
#define CHMFILE_CLOSED ((void *)0x1)

/* --- Capsule helpers ---------------------------------------------------- */

static struct chmFile *chmlib_get_chmfile(PyObject *chmfile_capsule) {
    if (!PyCapsule_IsValid(chmfile_capsule, CHMFILE_CAPSULE_NAME)) {
        PyErr_SetString(PyExc_ValueError, "Expected valid chmlib object");
        return NULL;
    }

    struct chmFile *chmfile = (struct chmFile *)PyCapsule_GetPointer(
        chmfile_capsule, CHMFILE_CAPSULE_NAME);

    if (chmfile == CHMFILE_CLOSED) {
        PyErr_SetString(PyExc_RuntimeError, "chmlib object is closed");
        return NULL;
    }

    return chmfile;
}

static void chmlib_chmfile_capsule_destructor(PyObject *chmfile_capsule) {
    struct chmFile *chmfile = chmlib_get_chmfile(chmfile_capsule);
    if (!chmfile) {
        PyErr_Clear();
        return;
    }

    chm_close(chmfile);
    PyCapsule_SetPointer(chmfile_capsule, CHMFILE_CLOSED);
}

/* --- chm_open ----------------------------------------------------------- */

static PyObject *chmlib_chm_open(PyObject *self, PyObject *args) {
    const char *filename;
    if (!PyArg_ParseTuple(args, "y:chm_open", &filename))
        return NULL;

    struct chmFile *chmfile = chm_open(filename);
    if (chmfile == NULL)
        Py_RETURN_NONE;

    return PyCapsule_New(chmfile, CHMFILE_CAPSULE_NAME,
                         chmlib_chmfile_capsule_destructor);
}

/* --- chm_close ---------------------------------------------------------- */

static PyObject *chmlib_chm_close(PyObject *self, PyObject *args) {
    PyObject *chmfile_capsule;
    if (!PyArg_ParseTuple(args, "O:chm_close", &chmfile_capsule))
        return NULL;

    chmlib_chmfile_capsule_destructor(chmfile_capsule);

    Py_RETURN_NONE;
}

/* --- Enumeration callback bridge ---------------------------------------- */

struct chmlib_enumerator_context {
    PyObject *chmfile_capsule;
    PyObject *py_enumerator;
    PyObject *py_context;
    int has_error;
};

static PyObject *chmUnitInfoTuple(struct chmUnitInfo *ui) {
    return Py_BuildValue("(KKiiy)", ui->start, ui->length, ui->space,
                         ui->flags, ui->path);
}

static int chmlib_chm_enumerator(struct chmFile *h, struct chmUnitInfo *ui,
                                  void *context) {
    struct chmlib_enumerator_context *ctx = context;
    long ret;

    PyObject *arglist = Py_BuildValue("(OOO)", ctx->chmfile_capsule,
                                      chmUnitInfoTuple(ui), ctx->py_context);
    if (arglist == NULL)
        goto fail;

    PyObject *result = PyObject_CallObject(ctx->py_enumerator, arglist);
    Py_DECREF(arglist);

    if (result == NULL)
        goto fail;

    if (result == Py_None) {
        Py_DECREF(result);
        return CHM_ENUMERATOR_CONTINUE;
    }

    if (!PyLong_Check(result)) {
        PyErr_Format(PyExc_RuntimeError,
                     "chm_enumerate callback should return int or None, got %R",
                     result);
        Py_DECREF(result);
        goto fail;
    }

    ret = PyLong_AsLong(result);
    Py_DECREF(result);
    if (ret == -1 && PyErr_Occurred() != NULL)
        goto fail;

    return (int)ret;

fail:
    ctx->has_error = 1;
    return CHM_ENUMERATOR_FAILURE;
}

/* --- chm_enumerate ------------------------------------------------------ */

static PyObject *chmlib_chm_enumerate(PyObject *self, PyObject *args) {
    PyObject *chmfile_capsule;
    int what;
    PyObject *enumerator;
    PyObject *context;

    if (!PyArg_ParseTuple(args, "OiOO:chm_enumerate", &chmfile_capsule,
                          &what, &enumerator, &context))
        return NULL;

    struct chmFile *chmfile = chmlib_get_chmfile(chmfile_capsule);
    if (!chmfile)
        return NULL;

    if (!PyCallable_Check(enumerator)) {
        PyErr_Format(PyExc_TypeError,
                     "A callable is expected for callback, got %R", enumerator);
        return NULL;
    }

    struct chmlib_enumerator_context ctx = {
        .chmfile_capsule = chmfile_capsule,
        .py_enumerator = enumerator,
        .py_context = context,
    };

    int res = chm_enumerate(chmfile, what, chmlib_chm_enumerator, &ctx);

    if (ctx.has_error)
        return NULL;

    return PyLong_FromLong(res);
}

/* --- chm_resolve_object ------------------------------------------------- */

static PyObject *chmlib_chm_resolve_object(PyObject *self, PyObject *args) {
    PyObject *chmfile_capsule;
    const char *path;
    struct chmUnitInfo ui;

    if (!PyArg_ParseTuple(args, "Oy:chm_resolve_object",
                          &chmfile_capsule, &path))
        return NULL;

    struct chmFile *chmfile = chmlib_get_chmfile(chmfile_capsule);
    if (!chmfile)
        return NULL;

    if (chm_resolve_object(chmfile, path, &ui) == CHM_RESOLVE_FAILURE)
        Py_RETURN_NONE;

    return chmUnitInfoTuple(&ui);
}

/* --- chm_retrieve_object ------------------------------------------------ */

static PyObject *chmlib_chm_retrieve_object(PyObject *self, PyObject *args) {
    PyObject *chmfile_capsule;
    unsigned long long uistart;
    unsigned long long uilength;
    int uispace;
    unsigned long long offset;
    long long length;

    if (!PyArg_ParseTuple(args, "OKKiKL:chm_retrieve_object",
                          &chmfile_capsule, &uistart, &uilength, &uispace,
                          &offset, &length))
        return NULL;

    struct chmFile *chmfile = chmlib_get_chmfile(chmfile_capsule);
    if (!chmfile)
        return NULL;

    if (length < 0) {
        PyErr_Format(PyExc_ValueError,
                     "Expected non-negative length, got %lld", length);
        return NULL;
    }

    PyObject *pybuf = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)length);
    if (!pybuf)
        return NULL;

    char *buf = PyBytes_AS_STRING(pybuf);

    struct chmUnitInfo ui = {
        .start = uistart,
        .length = uilength,
        .space = uispace,
    };

    long long res = chm_retrieve_object(chmfile, &ui,
                                        (unsigned char *)buf, offset, length);

    if (res == 0) {
        Py_DECREF(pybuf);
        Py_RETURN_NONE;
    }

    if (res != length)
        _PyBytes_Resize(&pybuf, (Py_ssize_t)res);

    return pybuf;
}

/* --- Module definition -------------------------------------------------- */

static PyMethodDef chmlib_methods[] = {
    {"chm_open", chmlib_chm_open, METH_VARARGS, "Open a CHM file"},
    {"chm_close", chmlib_chm_close, METH_VARARGS, "Close a CHM file"},
    {"chm_enumerate", chmlib_chm_enumerate, METH_VARARGS,
     "Enumerate objects in a CHM file"},
    {"chm_resolve_object", chmlib_chm_resolve_object, METH_VARARGS,
     "Resolve an object path in a CHM file"},
    {"chm_retrieve_object", chmlib_chm_retrieve_object, METH_VARARGS,
     "Retrieve object content from a CHM file"},
    {NULL},
};

static struct PyModuleDef chmlib_module = {
    PyModuleDef_HEAD_INIT,
    "_chmlib",
    "Python bindings for CHMLib (vendored)",
    -1,
    chmlib_methods,
};

PyMODINIT_FUNC PyInit__chmlib(void) {
    return PyModule_Create(&chmlib_module);
}
