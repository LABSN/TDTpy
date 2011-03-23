import os
import numpy as np
import ctypes

#import comtypes.client
# To use comptypes, zbus = comtypes.client.CreateObject('ZBUS.x')
#import win32com.client
# To use win32com, zbus = win32com.client.Dispatch('ZBUS.X')
import actxobjects
# To use actxobjects, zbus = actxobjects.ZBUSx()

from dsp_error import DSPError

import logging
log = logging.getLogger(__name__)
log.setLevel(logging.WARN)

INTERFACE = 'GB'

DRIVERS = {
        'RX6':  'RPcoX',
        'ZBUS': 'ZBUSx',
        'PA5':  'PA5x',
        'RZ5':  'RPcoX',
        'RZ6':  'RPcoX',
        }

def connect_zbus():
    '''
    Connect to the zBUS interface and set zBUS triggeres to low
    '''
    zbus = actxobjects.ZBUSx()
    #zbus = comtypes.client.CreateObject('ZBUS.x')
    if not zbus.ConnectZBUS(INTERFACE):
        raise DSPError("zBUS", "Connection failed")
    log.info("Connected to zBUS")

    # zBUS trigger is set to high for record mode, so ensure that both triggers
    # are initialized to low.
    zbus.zBusTrigA(0, 2, 10)
    zbus.zBusTrigB(0, 2, 10)
    log.info("Set zBusTrigA to low")
    log.info("Set zBusTrigB to low")
    return zbus

def connect(name, ID=1):
    '''
    Connect to device
    '''
    debug_string = '%s %d via %s interface' % (name, ID, INTERFACE)
    driver = getattr(actxobjects, DRIVERS[name])()
    if not getattr(driver, 'Connect%s' % name)(INTERFACE, ID):
        raise DSPError(name, "Connection failed")
    log.info("Connected to %s", name)
    return driver

def get_cof_path(circuit_name):
    '''
    Given relative path, returns absolute path to circuit file.  The *.rcx
    extension may be omitted.
    '''
    search_dirs = [os.path.join(os.path.dirname(__file__), 'components'),
                   os.getcwd(), ]
    log.debug("Searching %r", search_dirs)

    success = False
    if not circuit_name.endswith('.rcx'):
        circuit_name += '.rcx'

    log.info("Attempting to locate circuit %s", circuit_name)
    for dir in search_dirs:
        circuit_path = os.path.join(dir, circuit_name)
        log.info('Checking %s', circuit_path)
        if os.path.exists(circuit_path):
            success = True
            break

    if not success:
        raise IOError, "Could not find circuit %s" % circuit_name
    return circuit_path

def dtype_to_type_str(data_type):
    '''
    Convert Numpy dtype to the type string required by TDT's libraries

    TDT's ActiveX ReadTagVEX and WriteTagVEX functions require the type string
    to be one of I8, I16, I32 or F32.
    '''
    if np.issubdtype(data_type, np.int):
        type_code = 'I'
    elif np.issubdtype(data_type, np.float):
        type_code = 'F'
    else:
        raise ValueError, "Unsupported numpy dtype"

    # Since dtype.itemsize is the number of bytes, and the number in the TDT
    # type string reflects bit number, we can translate it by multiplying by 8.
    # Likewise, dtype.char is 'i' for integer and 'f' for floating point
    # datatypes.
    type_str = "{0}{1}".format(type_code, data_type.itemsize*8)
    log.info("%r TDT type string is %s", data_type, type_str)
    if type_str not in ['F32', 'I32', 'I16', 'I8']:
        raise ValueError, "Unsupported dtype"
    return type_str

def best_sf(data_type, range):
    '''
    Computes the optimal scaling factor for data compression

    Parameters
    ----------
    data_type
        Data type that values are being compressed to
    range : scalar or tuple
        Expected data range.  If scalar, assumes the value falls in the range
        (-range, range)
    '''
    data_type = np.dtype(data_type)
    max_val = np.abs(range).max()
    try:
        info = np.iinfo(data_type)
    except:
        info = np.finfo(data_type)
    return info.max/abs_max_amplitude

def resolution(data_type, scaling_factor):
    '''
    Computes resolution for data type given scaling factor

    Parameters
    ----------
    data_type : 
        Numpy data type (or string)
    scaling_factor : 
        Scaling factor applied to data
    '''
    data_type = np.dtype(data_type)
    if np.issubdtype(data_type, np.int):
        return 1/float(scaling_factor)
    else:
        raise ValueError, "Float data types not supported"

CTYPES_TO_NP = {
    ctypes.c_char   : np.int8, 
    ctypes.c_wchar  : np.int16, 
    ctypes.c_byte   : np.int8, 
    ctypes.c_ubyte  : np.uint8, 
    ctypes.c_short  : np.int16, 
    ctypes.c_ushort : np.uint16, 
    ctypes.c_int    : np.int32, 
    ctypes.c_uint   : np.int32, 
    ctypes.c_long   : np.int32, 
    ctypes.c_ulong  : np.int32,  
    ctypes.c_float  : np.float32, 
    ctypes.c_double : np.float64 
    }
# Reverse lookup
NP_TO_CTYPES = dict((np.dtype(v), k) for k, v in CTYPES_TO_NP.items())

def shmem_as_ndarray(raw_array):  
    '''
    Create a ndarray wrapper around shared memory space
    '''
    address = raw_array._wrapper.get_address() 
    size = raw_array._wrapper.get_size() 
    dtype = CTYPES_TO_NP[raw_array._type_] 
    class NDArrayView(object): 
        pass 
    d = NDArrayView() 
    d.__array_interface__ = { 
         'data'     : (address, False), 
         'typestr'  : np.dtype('uint8').str,
         'descr'    : np.dtype('uint8').descr,
         'shape'    : (size,), 
         'strides'  : None, 
         'version'  : 3 
    }     
    return np.asarray(d).view(dtype=dtype)  
