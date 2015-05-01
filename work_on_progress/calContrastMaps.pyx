# -*- coding: utf-8 -*-
"""
Created on Fri Feb 13 17:54:42 2015

@author: ajaver
"""
import numpy as np
cimport numpy as np
cimport cython
from libc.math cimport round as c_round;
from libc.math cimport sqrt

@cython.boundscheck(False)
cdef inline int getAbsDiff(int a, int b): 
    return a-b if a>b else b-a;

cdef inline int calcR(int a, int b):
    cdef double R;
    R = <double>(a*a + b*b);
    R = c_round(sqrt(R));
    return <int>R

def calContrastMaps(np.ndarray[np.int64_t, ndim=2] pix_dat, int map_R_range, int map_pos_range, int map_neg_range):
    cdef np.ndarray[np.int_t, ndim=2] Ipos = np.zeros([map_R_range, map_pos_range], dtype=np.int)
    cdef np.ndarray[np.int_t, ndim=2] Ineg = np.zeros([map_R_range, map_neg_range], dtype=np.int)
    
    cdef int i1, i2, ipos, ineg;
    cdef int n_pix = pix_dat.shape[1];
    cdef int R, delX, delY;
    
    for i1 in range(n_pix-1):
        for i2 in range(i1+1, n_pix):
            ipos = pix_dat[2,i1] + pix_dat[2,i2];
            ineg = getAbsDiff(pix_dat[2,i1] , pix_dat[2,i2])
            
            delX = pix_dat[0,i1]-pix_dat[0,i2];
            delY = pix_dat[1,i1]-pix_dat[1,i2];
            
            R = calcR(delX, delY);
            if R>=map_R_range:
                R = map_R_range-1;
            
            Ipos[R, ipos] += 1;
            Ineg[R, ineg] += 1;
            
    return (Ipos, Ineg);
